import os
import sys
import json
import datetime
import mimetypes
from collections import Counter
from django.conf import settings
from django.core.management import execute_from_command_line
from django.core.wsgi import get_wsgi_application
from django.urls import path
from django.http import JsonResponse, HttpResponse, FileResponse
from django.views.decorators.csrf import csrf_exempt

# --- 1. DOSYA YOLLARI VE AYARLAR ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Dosya İsimleri
FILES = {
    'decisions': 'decisions.json',
    'logs': 'access_logs.json',
    'announcements': 'announcements.json',
    'messages': 'messages.json',
    'passwords': 'passwords.json',
    'academicians': 'academicians_merged.json',
    'projects': 'eu_projects_merged_tum.json',
    'matches': 'n8n_akademisyen_proje_onerileri.json',
    'web_data': 'web_data.json'
}

# Tam Yollar
DECISIONS_FILE = os.path.join(BASE_DIR, FILES['decisions'])
LOGS_FILE = os.path.join(BASE_DIR, FILES['logs'])
ANNOUNCEMENTS_FILE = os.path.join(BASE_DIR, FILES['announcements'])
MESSAGES_FILE = os.path.join(BASE_DIR, FILES['messages'])
PASSWORDS_FILE = os.path.join(BASE_DIR, FILES['passwords'])

# Mime Type Ayarı (Windows/Linux uyumu için)
mimetypes.init()
mimetypes.add_type("application/javascript", ".js", True)
mimetypes.add_type("text/css", ".css", True)

# app.py içindeki settings.configure bloğunu bul ve BUNUNLA DEĞİŞTİR:

if not settings.configured:
    settings.configure(
        DEBUG=False, # Canlıda False
        SECRET_KEY='gizli-anahtar-render-icin',
        ROOT_URLCONF=__name__,
        ALLOWED_HOSTS=['*'], # Her yerden erişime izin ver (Host izni)
        
        INSTALLED_APPS=[
            'django.contrib.staticfiles',
            'django.contrib.contenttypes',
            'django.contrib.auth',
            'corsheaders',  # <--- BU MUTLAKA OLMALI
        ],
        
        MIDDLEWARE=[
            'corsheaders.middleware.CorsMiddleware', # <--- BU EN TEPEDE OLMALI (Çok Önemli!)
            'django.middleware.security.SecurityMiddleware',
            'whitenoise.middleware.WhiteNoiseMiddleware',
            'django.middleware.common.CommonMiddleware',
            # Diğer middleware'ler...
        ],
        
        # --- CORS AYARLARI (KAPIYI AÇAN KISIM) ---
        CORS_ALLOW_ALL_ORIGINS=True, # Herkese izin ver
        CORS_ALLOW_CREDENTIALS=True, # Kimlik bilgilerine izin ver
        
        # Hangi metodlara izin verilecek?
        CORS_ALLOW_METHODS=[
            'DELETE',
            'GET',
            'OPTIONS',
            'PATCH',
            'POST',
            'PUT',
        ],
        
        # Hangi başlıklara (headers) izin verilecek?
        CORS_ALLOW_HEADERS=[
            'accept',
            'accept-encoding',
            'authorization',
            'content-type',
            'dnt',
            'origin',
            'user-agent',
            'x-csrftoken',
            'x-requested-with',
        ],

        # Statik Dosya Ayarları
        STATIC_URL='/static/',
        STATIC_ROOT=os.path.join(BASE_DIR, 'staticfiles'),
    )

# --- 2. VERİTABANI VE YÜKLEME ---
DB = {
    'ACADEMICIANS_BY_NAME': {},
    'ACADEMICIANS_BY_EMAIL': {},
    'PROJECTS': {},
    'MATCHES': [],
    'FEEDBACK': [],
    'LOGS': [],
    'ANNOUNCEMENTS': [],
    'MESSAGES': [],
    'PASSWORDS': {},
    'WEB_DATA': {}
}

def load_data():
    """Tüm JSON dosyalarını hafızaya yükler."""
    # 1. Akademisyenler
    try:
        with open(os.path.join(BASE_DIR, FILES['academicians']), 'r', encoding='utf-8') as f:
            data = json.load(f)
            for p in data:
                if p.get("Fullname"): DB['ACADEMICIANS_BY_NAME'][p["Fullname"].strip().upper()] = p
                if p.get("Email"): DB['ACADEMICIANS_BY_EMAIL'][p["Email"].strip().lower()] = p
    except Exception as e: print(f"Hata - Akademisyenler: {e}")

    # 2. Projeler
    try:
        with open(os.path.join(BASE_DIR, FILES['projects']), 'r', encoding='utf-8') as f:
            data = json.load(f)
            # Liste ise döngüye sok, sözlük ise direkt al
            if isinstance(data, list):
                for p in data:
                    pid = str(p.get("project_id", "")).strip()
                    if pid: DB['PROJECTS'][pid] = p
            elif isinstance(data, dict):
                 # Eğer JSON { "101..": {...} } formatındaysa
                 for pid, p in data.items():
                     DB['PROJECTS'][str(pid)] = p
    except Exception as e: print(f"Hata - Projeler: {e}")

    # 3. Eşleşmeler
    try:
        with open(os.path.join(BASE_DIR, FILES['matches']), 'r', encoding='utf-8') as f:
            data = json.load(f)
            # n8n çıktısı bazen iç içe liste olabilir, düzeltiyoruz:
            raw_list = []
            if isinstance(data, dict):
                for key, val in data.items():
                    if isinstance(val, list): raw_list.extend(val)
            elif isinstance(data, list):
                raw_list = data
            
            for item in raw_list:
                # İsim ve Proje ID'yi güvenli al
                name = item.get('data') or item.get('academician_name')
                pid = str(item.get('Column3') or item.get('project_id') or "")
                
                # Gereksiz başlık satırlarını ele
                if name and pid and name != "academician_name":
                    score = item.get('Column7') or item.get('score') or 0
                    try: score = int(score)
                    except: score = 0
                    DB['MATCHES'].append({"name": name.strip(), "projId": pid, "score": score})
    except Exception as e: print(f"Hata - Eşleşmeler: {e}")

    # 4. Diğer Basit Dosyalar
    for key, filename in [('FEEDBACK', FILES['decisions']), ('LOGS', FILES['logs']), 
                          ('ANNOUNCEMENTS', FILES['announcements']), ('MESSAGES', FILES['messages']), 
                          ('PASSWORDS', FILES['passwords']), ('WEB_DATA', FILES['web_data'])]:
        path_ = os.path.join(BASE_DIR, filename)
        if os.path.exists(path_):
            try:
                with open(path_, 'r', encoding='utf-8') as f:
                    DB[key] = json.load(f)
            except: pass

# Uygulama başlarken verileri yükle
load_data()

# --- 3. YARDIMCI FONKSİYONLAR ---
def save_json(path, data):
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception as e: print(f"Kaydetme Hatası: {e}")

def get_safe_title(pd, pid):
    """Proje başlığı yoksa alternatifleri dener."""
    if not pd: return f"Proje-{pid}"
    
    title = pd.get("title")
    if not title: title = pd.get("acronym") # Başlık yoksa kısaltmayı al
    if not title: title = pd.get("project_acronym")
    if not title: title = f"Proje-{pid}" # Hiçbiri yoksa ID yaz
    return title

# --- 4. API ENDPOINTLERİ ---

def index(request):
    return HttpResponse("Backend Calisiyor (Render Deployment)")

@csrf_exempt
def api_login(request):
    try:
        d = json.loads(request.body)
        u = d.get('username', '').strip().lower()
        p = d.get('password', '').strip()
        
        # Admin Girişi
        if u == "admin" and p == "12345":
            return JsonResponse({"status": "success", "role": "admin", "name": "Yönetici"})
        
        # Akademisyen Girişi
        if u in DB['ACADEMICIANS_BY_EMAIL']:
            real_pass = DB['PASSWORDS'].get(u, u.split('@')[0]) # Şifre yoksa email prefixi
            if p == real_pass:
                acc = DB['ACADEMICIANS_BY_EMAIL'][u]
                return JsonResponse({"status": "success", "role": "academician", "name": acc["Fullname"]})
        
        return JsonResponse({"status": "error", "message": "Gecersiz kullanici"}, status=401)
    except: return JsonResponse({}, 400)

@csrf_exempt
def api_profile(request):
    try:
        body = json.loads(request.body)
        name = body.get('name')
        if not name: return JsonResponse({}, 400)

        raw = DB['ACADEMICIANS_BY_NAME'].get(name.upper())
        if not raw: return JsonResponse({"error": "Bulunamadi"}, 404)

        # Fotoğraf Bulma Mantığı
        base_url = "https://estu-portal-backend.onrender.com" # Canlı URL
        img_final = None
        
        # 1. web_data.json'dan bak
        if isinstance(DB['WEB_DATA'], list):
            for w in DB['WEB_DATA']:
                if w.get("Fullname", "").upper() == name.upper():
                    path_ = w.get("Image_Path")
                    if path_: img_final = f"{base_url}/{path_}"
                    break
        
        # 2. Eğer yoksa klasörden bulmaya çalış
        if not img_final:
            email_user = raw.get("Email", "").split('@')[0].lower()
            folder = os.path.join(BASE_DIR, 'akademisyen_fotograflari')
            if os.path.exists(folder):
                for f in os.listdir(folder):
                    if f.lower().startswith(email_user):
                        img_final = f"{base_url}/akademisyen_fotograflari/{f}"
                        break
        
        # Projeleri Eşleşmelerden Çek
        matches = [m for m in DB['MATCHES'] if m["name"].upper() == name.upper()]
        projects = []
        
        for m in matches:
            pid = m["projId"]
            pd = DB['PROJECTS'].get(pid, {})
            
            # Karar Durumu
            decision = "waiting"
            for fb in DB['FEEDBACK']:
                if fb.get("academician") == name and fb.get("projId") == pid:
                    decision = fb.get("decision")
                    break
            
            # GÜVENLİ BAŞLIK FONKSİYONU
            safe_title = get_safe_title(pd, pid)

            projects.append({
                "id": pid,
                "score": m["score"],
                "title": safe_title,
                "status": pd.get("status", "-"),
                "budget": pd.get("overall_budget", "-"),
                "objective": pd.get("objective", "")[:300] + "...", # Özet geç
                "decision": decision,
                "url": pd.get("url", "#")
            })
            
        # Skora göre sırala
        projects.sort(key=lambda x: x['score'], reverse=True)

        return JsonResponse({
            "profile": {
                "Fullname": raw.get("Fullname"),
                "Email": raw.get("Email"),
                "Image": img_final,
                "Title": raw.get("Title", "Akademisyen"),
                "Duties": raw.get("Duties", [])
            },
            "projects": projects
        })
    except Exception as e: return JsonResponse({"error": str(e)}, 500)

@csrf_exempt
def api_top_projects(request):
    # En çok eşleşen projeleri bul
    cnt = Counter(m['projId'] for m in DB['MATCHES']).most_common(50)
    top = []
    for pid, c in cnt:
        pd = DB['PROJECTS'].get(pid, {})
        safe_title = get_safe_title(pd, pid) # Güvenli Başlık
        
        top.append({
            "id": pid,
            "count": c,
            "title": safe_title,
            "budget": pd.get("overall_budget", "-"),
            "status": pd.get("status", "-"),
            "url": pd.get("url", "#")
        })
    return JsonResponse(top, safe=False)

@csrf_exempt
def api_project_decision(request):
    try:
        d = json.loads(request.body)
        acc = d.get("academician")
        pid = d.get("projId")
        
        # Varsa güncelle, yoksa ekle
        found = False
        for item in DB['FEEDBACK']:
            if item["academician"] == acc and item["projId"] == pid:
                item.update(d)
                found = True
                break
        if not found:
            DB['FEEDBACK'].append(d)
            
        save_json(DECISIONS_FILE, DB['FEEDBACK'])
        return JsonResponse({"status": "success"})
    except: return JsonResponse({}, 400)

# --- 5. RESİM SUNMA (STATİK DOSYA GİBİ) ---
def serve_file(request, folder_name, filename):
    """Resim dosyalarını okuyup döner."""
    clean_name = os.path.basename(filename).lower()
    folder_path = os.path.join(BASE_DIR, folder_name)
    
    if os.path.exists(folder_path):
        for f in os.listdir(folder_path):
            if f.lower() == clean_name:
                return FileResponse(open(os.path.join(folder_path, f), 'rb'))
    
    return HttpResponse("Resim Bulunamadi", status=404)

# --- 6. URL YÖNLENDİRMELERİ ---
urlpatterns = [
    path('', index), # Anasayfa (Health Check için)
    path('api/login/', api_login),
    path('api/profile/', api_profile),
    path('api/decision/', api_project_decision),
    path('api/top-projects/', api_top_projects),
    
    # Resim Yolları
    path('images/<str:filename>', lambda r, filename: serve_file(r, 'images', filename)),
    path('akademisyen_fotograflari/<str:filename>', lambda r, filename: serve_file(r, 'akademisyen_fotograflari', filename)),
]

# --- 7. WSGI UYGULAMASI ---
application = get_wsgi_application()

if __name__ == "__main__":
    execute_from_command_line(sys.argv)
