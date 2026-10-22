import os, json, io, re, urllib.request, urllib.parse, cgi
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
import fitz
from PIL import Image
import pytesseract

ROOT = Path(__file__).parent
DOMAINS = {"Metro":"metro.pe", "Plaza Vea":"plazavea.com.pe", "Tottus":"tottus.com.pe", "Tai Loy":"tailoy.com.pe"}

class Handler(BaseHTTPRequestHandler):
    def send_json(self, code, payload):
        b=json.dumps(payload,ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type","application/json; charset=utf-8")
        self.send_header("Content-Length",str(len(b)))
        self.send_header("Cache-Control","no-store")
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        route=urllib.parse.urlsplit(self.path).path
        if route=="/api/health":
            return self.send_json(200, {"ok":True,"configured":bool(os.getenv("BRIGHTDATA_API_KEY") and os.getenv("BRIGHTDATA_SERP_ZONE"))})
        if route not in ("/","/index.html"):
            return self.send_error(404)
        data=(ROOT/"index.html").read_bytes()
        self.send_response(200)
        self.send_header("Content-Type","text/html; charset=utf-8")
        self.send_header("Content-Length",str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        route=urllib.parse.urlsplit(self.path).path
        length=int(self.headers.get("Content-Length","0"))
        if length<1 or length>31_500_000:
            return self.send_json(413,{"error":"Solicitud vacía o demasiado grande"})
        body=self.rfile.read(length)
        try:
            if route=="/api/extract":
                form=cgi.FieldStorage(fp=io.BytesIO(body),headers=self.headers,environ={"REQUEST_METHOD":"POST","CONTENT_TYPE":self.headers.get("Content-Type","")})
                upload=form["file"]
                pdf=upload.file.read(30_000_001)
                if not pdf.startswith(b"%PDF-") or len(pdf)>30_000_000:
                    return self.send_json(400,{"error":"PDF inválido o de más de 30 MB"})
                doc=fitz.open(stream=pdf,filetype="pdf")
                text=[]; scanned=0
                for page in list(doc)[:30]:
                    extracted=page.get_text("text",sort=True)
                    if len(extracted.strip())<15:
                        pix=page.get_pixmap(matrix=fitz.Matrix(2,2))
                        im=Image.open(io.BytesIO(pix.tobytes("png")))
                        extracted=pytesseract.image_to_string(im,lang="spa")
                        scanned+=1
                    text.append(extracted)
                return self.send_json(200,{"text":"\n".join(text),"pages":min(doc.page_count,30),"ocrPages":scanned,"truncated":doc.page_count>30})
            if route=="/api/prices":
                obj=json.loads(body)
                product=str(obj.get("product","")).strip()[:200]
                if not product:
                    return self.send_json(400,{"error":"Falta producto"})
                token=os.getenv("BRIGHTDATA_API_KEY")
                zone=os.getenv("BRIGHTDATA_SERP_ZONE")
                if not token or not zone:
                    return self.send_json(200,{"configured":False,"quotes":[],"message":"Proveedor de precios todavía no configurado."})
                q=product+" (site:metro.pe OR site:plazavea.com.pe OR site:tottus.com.pe OR site:tailoy.com.pe)"
                url="https://www.google.com/search?"+urllib.parse.urlencode({"q":q,"gl":"pe","hl":"es","brd_json":"1"})
                req=urllib.request.Request("https://api.brightdata.com/request",data=json.dumps({"zone":zone,"url":url,"format":"raw"}).encode(),headers={"Authorization":"Bearer "+token,"Content-Type":"application/json"},method="POST")
                with urllib.request.urlopen(req,timeout=45) as r:
                    response=json.loads(r.read(2_000_000))
                if isinstance(response.get("body"),str):
                    try: response=json.loads(response["body"])
                    except ValueError: pass
                results=response.get("organic",[]) if isinstance(response,dict) else []
                quotes=[]
                terms=set(re.findall(r"[\wáéíóúñ]+",product.lower()))-{"de","el","la","y","con","para"}
                for row in results:
                    link=str(row.get("link") or row.get("url") or "")
                    title=str(row.get("title") or "")
                    if not link.startswith("https://"):continue
                    host=urllib.parse.urlsplit(link).hostname or ""
                    shop=next((name for name,domain in DOMAINS.items() if host==domain or host.endswith("."+domain)),None)
                    if not shop:continue
                    words=set(re.findall(r"[\wáéíóúñ]+",title.lower()))
                    if terms and len(words&terms)/len(terms)<0.65:continue
                    match=re.search(r"(?:S/|PEN)\s*([\d,.]+)",title+" "+str(row.get("snippet","")),re.I)
                    if not match:continue
                    try: price=float(match.group(1).replace(",",""))
                    except ValueError:continue
                    if 0<price<100000:
                        quotes.append({"shop":shop,"title":title,"price":price,"url":link,"source":"Resultado web; verificar"})
                return self.send_json(200,{"configured":True,"quotes":quotes})
            return self.send_json(404,{"error":"Ruta desconocida"})
        except Exception:
            return self.send_json(422,{"error":"No se pudo procesar la solicitud. Verifica documento, proveedor y configuración."})

if __name__=="__main__":
    ThreadingHTTPServer(("0.0.0.0",int(os.getenv("PORT","8000"))),Handler).serve_forever()
