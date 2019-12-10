FROM python:3.7-alpine
ADD ./src /opt/app
WORKDIR /opt/app
RUN adduser -D -u 120002 -h /opt/app app \
    && mkdir .ssh \
    && sed -i 's/dl-cdn.alpinelinux.org/mirrors.aliyun.com/g' /etc/apk/repositories \
    && echo "StrictHostKeyChecking=no" > .ssh/config \
    && apk add gcc musl-dev libffi-dev make tzdata openssl-dev linux-headers openssh-client \
    && cp /usr/share/zoneinfo/Asia/Shanghai /etc/localtime \
    && pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ -r requirements.txt\
    && apk del libffi-dev tzdata gcc make linux-headers openssl-dev musl-dev\
    && rm -rf /var/cache/apk/*
ADD id_rsa  /opt/app/.ssh/
RUN chown -R app:app /opt/app
USER app
EXPOSE 8080
CMD ["python", "-u", "aliops.py"]