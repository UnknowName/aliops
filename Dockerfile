FROM docker.1ms.run/python:3.8-alpine
ENV CRYPTOGRAPHY_DONT_BUILD_RUST=1 \
    TZ=Asia/Shanghai
ADD ./src /opt/app
ADD ./requirements.txt /opt/app
WORKDIR /opt/app
RUN adduser -D -u 120002 -h /opt/app app \
    && mkdir .ssh \
    && sed -i 's/dl-cdn.alpinelinux.org/mirrors.aliyun.com/g' /etc/apk/repositories \
    && echo "StrictHostKeyChecking=no" > .ssh/config \
    && apk add gcc musl-dev libffi-dev make tzdata openssl-dev linux-headers openssh-client \
    && cp /usr/share/zoneinfo/Asia/Shanghai /etc/localtime \
    && pip install -i https://mirrors.aliyun.com/pypi/simple/ --no-cache-dir -r requirements.txt \
    && apk del libffi-dev gcc make linux-headers openssl-dev musl-dev \
    && rm -rf /var/cache/apk/*
ADD id_rsa  /opt/app/.ssh/
RUN chmod 600 /opt/app/.ssh/* \
    && chown -R app:app /opt/app
USER app
EXPOSE 8080
CMD ["python", "-u", "aliops.py"]