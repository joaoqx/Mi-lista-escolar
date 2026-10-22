FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-spa && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir PyMuPDF==1.26.5 pytesseract==0.3.13 Pillow==11.3.0
WORKDIR /app
COPY index.html server.py ./
ENV PORT=8000
EXPOSE 8000
CMD ["python","server.py"]
