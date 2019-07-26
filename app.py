import json
import signal
import os
import time
import logging
from datetime import datetime
import boto3
from hashlib import md5
from kafka import KafkaConsumer

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
KAFKA_TOPIC = os.environ.get('KAFKA_TOPIC')
KAFKA_CONSUMER_GROUP = os.environ.get('KAFKA_CONSUMER_GROUP')
MONGO_CONNECTION_STRING = os.environ.get('MONGO_CONNECTION_STRING')
MONGO_DB_NAME = os.environ.get('MONGO_DB_NAME')

consumer = KafkaConsumer(group_id=f"{KAFKA_CONSUMER_GROUP}", bootstrap_servers=KAFKA_HOST)
consumer.subscribe([f"{KAFKA_TOPIC}"])

def get_hotel_detail(href):
    options = Options()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    new_tab = webdriver.Chrome(options=options)
    new_tab.get(href)
    
    try:
        WebDriverWait(new_tab, 30).until(
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

if __name__ == "__main__":
    mongodb = pymongo.MongoClient(MONGO_CONNECTION_STRING)
    signal.signal(signal.SIGTERM, lambda : mongodb.close())  # Close db connection if receive termination

    try:
        for msg in consumer:
            db = mongodb[MONGO_DB_NAME]

            topic = msg.topic
            offset = msg.offset
            consumer.commit()
            hotels = db['agoda']

            body = msg.value.decode('utf-8')
            body = json.loads(body)['body']
            
            hotel_href = body.get('href')
            detail = get_hotel_detail(hotel_href)
            hotel_id = detail.get('id')

            hotels.update_one({"_id": hotel_id}, {"$set": detail}, upsert=True)
            logging.info("Hotel: " + json.dumps(detail))

    except Exception as e:
        mongodb.close()
        traceback.print_exc()
