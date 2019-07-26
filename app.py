import json
import signal
import os
import time
import logging
from datetime import datetime
import boto3
from hashlib import md5
from kafka import KafkaConsumer
import requests

from seleniumwire import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.common.touch_actions import TouchActions
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException
import sys
import traceback
import re
import random
import pymongo
from bson.objectid import ObjectId

logging.basicConfig(level=logging.INFO)

KAFKA_HOST = os.environ.get('KAFKA_HOST')
KAFKA_AGODA_TOPIC = os.environ.get('KAFKA_AGODA_TOPIC')
KAFKA_FINDHOTELS_TOPIC = os.environ.get('KAFKA_FINDHOTELS_TOPIC')

KAFKA_CONSUMER_GROUP = os.environ.get('KAFKA_CONSUMER_GROUP')
MONGO_CONNECTION_STRING = os.environ.get('MONGO_CONNECTION_STRING')
MONGO_DB_NAME = os.environ.get('MONGO_DB_NAME')

consumer = KafkaConsumer(group_id=f"{KAFKA_CONSUMER_GROUP}", bootstrap_servers=KAFKA_HOST)
consumer.subscribe([f"{KAFKA_AGODA_TOPIC}", f"{KAFKA_FINDHOTELS_TOPIC}"])

def craw_agoda_detail(href):
    options = Options()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    new_tab = webdriver.Chrome(options=options)
    new_tab.get(href)
    
    try:
        WebDriverWait(new_tab, 10).until(
            EC.presence_of_element_located((By.XPATH, '//div[@id="reviewSection"]'))
        )
    except Exception:
        traceback.print_exc()
    
    # print(new_tab.requests)
    reqs = [req for req in new_tab.requests \
            if req.method == 'GET' and len(re.findall('agoda.com/api/en-us/pageparams/property?', req.path))]
    # print(reqs)
    detail = reqs[-1].response
    body = detail.body
    info = json.loads(body)
    hotelInfo = info.get('hotelInfo')
    mapInfo = info.get('mapParams')
    rooms = info.get('datelessMasterRoomInfo')
    def get_room_info(room):
        return {
            "name": room.get('name'),
            "images": room.get('images'),
            "thumbnails": room.get('thumbnailsList'),
        }
    
    result = {
        "id": info.get('hotelId'),
        "name": hotelInfo.get('name'),
        "englishName": hotelInfo.get('englishName'),
        "accommodationType": hotelInfo.get('accommodationType'),
        "starRating": hotelInfo.get('starRating').get('value'),
        "address": hotelInfo.get('address').get('full'),
        "addressShort": hotelInfo.get('address').get('address'),
        "country": hotelInfo.get('address').get('countryName'),
        "city": hotelInfo.get('address').get('cityName'),
        "area": hotelInfo.get('address').get('areaName'),
        "postalCode": hotelInfo.get('address').get('postalCode'),
        "lat": str(mapInfo.get('latlng')[0]),
        "lng": str(mapInfo.get('latlng')[1]),
        "reviewScore": mapInfo.get('review').get('score'),
        "reviewCount": mapInfo.get('review').get('reviewCount'),
        "imageUrl": mapInfo.get('review').get('hotelImageUrl'),
        "rooms": list(map(get_room_info, rooms)) if rooms else []
    }
    new_tab.close()
    return result


def craw_findhotels(lat, lng):
    sizeGet = 1000
    findHotelApiHost = r"https://4uygjp42kq-dsn.algolia.net/1/indexes/prod_hotel_v2/query?x-algolia-agent=Algolia%20for%20vanilla%20JavaScript%203.32.0&x-algolia-application-id=4UYGJP42KQ&x-algolia-api-key=efa703d5c0057a24487bc9bdcb597770&x-algolia-usertoken=d00c47a3-6590-4ed2-873b-97e873e205b8"
    body = {
        "params": f"page=0&hitsPerPage={sizeGet}&facets=%5B%22*%22%5D&filters=isDeleted%20%3D%200&facetFilters=%5B%5D&numericFilters=%5B%5D&optionalFilters=%5B%5D&attributesToRetrieve=%5B%22_geoloc%22%2C%22chainId%22%2C%22checkInTime%22%2C%22checkOutTime%22%2C%22facilities%22%2C%22guestRating%22%2C%22guestType%22%2C%22imageURIs%22%2C%22popularity%22%2C%22propertyTypeId%22%2C%22reviewCount%22%2C%22starRating%22%2C%22themeIds%22%2C%22objectID%22%2C%22lastBooked%22%2C%22isDeleted%22%2C%22pricing%22%2C%22sentiments%22%2C%22displayAddress.en%22%2C%22guestSentiments.en%22%2C%22hotelName.en%22%2C%22placeDisplayName.en%22%2C%22placeADName.en%22%2C%22placeDN.en%22%2C%22address.en%22%5D&attributesToHighlight=null&getRankingInfo=true&clickAnalytics=true&aroundLatLng={lat}%2C%20{lng}&aroundRadius=20000&aroundPrecision=2000"
    }
    result = requests.post(findHotelApiHost, json=body)
    hits = json.loads(result.content)['hits']

    return hits


if __name__ == "__main__":
    mongodb = pymongo.MongoClient(MONGO_CONNECTION_STRING)
    db = mongodb[MONGO_DB_NAME]
    signal.signal(signal.SIGTERM, lambda : mongodb.close())  # Close db connection if receive termination

    try:
        for msg in consumer:
            topic = msg.topic
            offset = msg.offset

            body = msg.value.decode('utf-8')
            body = json.loads(body)['body']
            
            hotel_source = body.get('source')

            # Craw hotel data from agoda.com
            if topic == KAFKA_AGODA_TOPIC:
                hotels = db['Agoda']
                hotel_href = body.get('href')
                try:
                    detail = craw_agoda_detail(hotel_href)
                    hotel_id = detail.get('id')

                    hotels.update_one({"_id": hotel_id}, {"$set": detail}, upsert=True)
                    logging.info("Hotel: " + json.dumps(detail))
                except Exception as e:
                    traceback.print_exc()
            
            # Craw hotel data from findhotels.com
            elif topic == KAFKA_FINDHOTELS_TOPIC:
                hotels = db['FindHotels']
                lat = body.get('lat')
                lng = body.get('lng')
                try:
                    items = craw_findhotels(lat, lng)
                    for item in items:
                        hotels.update_many({"_id": item['objectID']}, {"$set": item}, upsert=True)
                    logging.info(f'Found {len(items)} hotel from Findhotels')
                except Exception as e:
                    traceback.print_exc()

    except Exception as e:
        mongodb.close()
        traceback.print_exc()
