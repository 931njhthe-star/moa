FROM python:3.11-slim

WORKDIR /app

# 공유 카드 PNG 의 한글 폰트 (API-033 format=image).
# slim 이미지에는 한글 글리프가 없어서, 없으면 글자가 두부(네모)로 찍힌 그림이 나간다.
# share_image.available() 이 이 폰트를 찾아 image_available 을 정한다
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-nanum fontconfig \
    && fc-cache -f \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]