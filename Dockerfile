FROM python:3.7

# update apk repo
RUN echo "http://dl-4.alpinelinux.org/alpine/v3.8/main" >> /etc/apk/repositories && \
    echo "http://dl-4.alpinelinux.org/alpine/v3.8/community" >> /etc/apk/repositories

# install chromedriver
RUN apk update
RUN apk add chromium chromium-chromedriver
RUN apk add openssl

# Create app directory
WORKDIR /usr/src/app

# Install app dependencies
# A wildcard is used to ensure both package.json AND package-lock.json are copied
# where available (npm@5+)
RUN pip install boto3==1.9.152
RUN pip install kafka-python==1.4.6
RUN pip install selenium==3.141.0
RUN pip install selenium-wire==1.0.5
RUN pip install pymongo==3.8.0

# Bundle app source
COPY . .

CMD [ "python", "app.py" ]