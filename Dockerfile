FROM python:3.13.3-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE 1 \ 
PYTHONUNBUFFERED 1 

WORKDIR /app

RUN apt-get update && apt-get install -y curl git

COPY app/requirements.txt .
RUN pip install -r requirements.txt

COPY app/ .

EXPOSE 8000

CMD ["./entrypoint.sh"]
