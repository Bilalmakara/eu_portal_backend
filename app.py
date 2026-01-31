import os
import sys
import json
import mimetypes
from django.conf import settings
from django.core.management import execute_from_command_line
from django.core.wsgi import get_wsgi_application
from django.urls import path
from django.http import JsonResponse, HttpResponse, FileResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils.deprecation import MiddlewareMixin

# --- 1. DOSYA YOLLARI VE AYARLAR ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Dosya İsimleri (Senin dosya isimlerinle birebir aynı)
FILES = {
    'decisions': os.path.join(BASE_DIR, 'decisions.json'),
    'matches': os.path.join(BASE_DIR, 'n8n_akademisyen_proje_onerileri.json'),
    'projects': os.path.join(BASE_DIR, 'eu_projects_merged_tum.json'),
    'academicians': os.path.join(BASE_DIR, 'academicians_merged.json'),
    'web_data': os.path.join(BASE_DIR, 'web_data.json'),
    'messages': os.path.join(BASE_DIR, 'messages.json'),
    'announcements': os.path.join(BASE_DIR, 'announcements.json'),
    'logs': os.path.join(BASE_DIR, 'access_logs.json'),
    'passwords': os.path.join(BASE_DIR, 'passwords.json')
}

# --- 2. MANUEL CORS BEKÇİSİ (Kütüphanesiz Kesin Çözüm) ---
class CorsMiddleware(MiddlewareMixin):
    def process_response(self, request, response):
        response["Access-Control-Allow-Origin"] = "*"  # Kapıyı herkese aç
        response["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        response["Access-Control-Allow-Headers"] = "*" # Tüm başlıklara izin ver
        return response

# --- 3. DJANGO AYARLARI ---
if not settings.configured:
    settings.configure(
        DEBUG=True, # Hataları görmek için AÇIK
        SECRET_KEY='gizli-anahtar-render-icin',
        ROOT_URLCONF=__name__,
        ALLOWED_HOSTS=['*'], # Her yerden erişim
        INSTALLED_APPS=[
            'django.contrib.staticfiles',
            'django.contrib.contenttypes',
            'django.contrib.auth',
        ],
        MIDDLEWARE=[
            'app.CorsMiddleware', # <--- BİZİM YAZDIĞIMIZ BEKÇİ EN BAŞTA!
            'django.middleware.common.CommonMiddleware',
            'django.middleware.csrf.CsrfViewMiddleware',
        ],
        STATIC_URL='/static/',
        STATIC_ROOT=os.path.join(BASE_DIR, 'staticfiles'),
    )

# --- 4. VERİLERİ YÜKLEME ---
DB = { 'PROJECTS': {}, 'ACADEMICIANS': {}, 'MATCHES': [], 'FEEDBACK': [], 'WEB_DATA': [], 'MESSAGES': [], 'ANNOUNCEMENTS': [], 'LOGS': [], 'PASSWORDS': {} }

def safe_load(key, filepath, is_list=False):
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except: pass
    return [] if is_list else {}

# Verileri Belleğe Al
DB['FEEDBACK'] = safe_load('FEEDBACK', FILES['decisions'], True)
DB['MATCHES'] = safe_load('MATCHES', FILES['matches'], True)
DB['WEB_DATA'] = safe_load('WEB_DATA', FILES['web_data'], True)
DB['MESSAGES'] = safe_load('MESSAGES', FILES['messages'], True)
DB['ANNOUNCEMENTS'] = safe_load('ANNOUNCEMENTS', FILES['announcements'], True)
DB['PASSWORDS'] = safe_load('PASSWORDS', FILES['passwords'], False)
DB['LOGS'] = safe_load('LOGS', FILES['logs'], True)

# Projeleri Sözlük Yap
raw_projects = safe_load('PROJECTS', FILES['projects'], True)
if isinstance(raw_projects, list):
    for p in raw_projects:
        pid = str(p.get("project_id", "")).strip()
        if pid: DB['PROJECTS'][pid] = p
elif isinstance(raw_projects, dict):
    DB['PROJECTS'] = raw_projects

# Akademisyenleri Sözlük Yap
raw_academicians = safe_load('ACADEMICIANS', FILES['academicians'], True)
for p in raw_academicians:
    if p.get("Email"): DB['ACADEMICIANS'][p["Email"].strip().lower()] = p

# --- 5. VIEW FONKSİYONLARI ---

def index(request):
    return HttpResponse("Backend Calisiyor! (V2 - Manuel CORS)")

@csrf_exempt
def api_login(request):
    if request.method == "OPTIONS": return JsonResponse({}) # Tarayıcı kontrolüne "Evet" de
    try:
        d = json.loads(request.body)
        u = d.get('username', '').lower().strip()
        p = d.get('password', '').strip()
        
        # Admin Girişi
        if u == "admin" and p == "12345":
            return JsonResponse({"status": "success", "role": "admin", "name": "Yönetici"})
            
        # Akademisyen Girişi
        if u in DB['ACADEMICIANS']:
            real_pass = DB['PASSWORDS'].get(u, u.split('@')[0]) # Şifre yoksa email prefixi
            if p == real_pass:
                acc = DB['ACADEMICIANS'][u]
                return JsonResponse({"status": "success", "role": "academician", "name": acc["Fullname"]})
        
        return JsonResponse({"status": "error", "message": "Hatali giris"}, status=401)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)

@csrf_exempt
def api_profile(request):
    if request.method == "OPTIONS": return JsonResponse({})
    try:
        body = json.loads(request.body)
        name = body.get('name')
        
        # Akademisyen Bilgisi
        acc = None
        for email, p in DB['ACADEMICIANS'].items():
            if p.get("Fullname") == name:
                acc = p
                break
        
        if not acc: return JsonResponse({"error": "Bulunamadi"}, 404)

        # Projeleri Bul
        my_matches = [m for m in DB['MATCHES'] if isinstance(m, dict) and (m.get('data') == name or m.get('academician_name') == name)]
        
        projects = []
        for m in my_matches:
            pid = str(m.get('Column3') or m.get('project_id') or "")
            pd = DB['PROJECTS'].get(pid, {})
            title = pd.get("title") or pd.get("acronym") or f"Proje-{pid}"
            
            # Karar Durumu
            decision = "waiting"
            for fb in DB['FEEDBACK']:
                if fb.get("academician") == name and fb.get("projId") == pid:
                    decision = fb.get("decision")
                    break
            
            projects.append({
                "id": pid,
                "title": title,
                "score": int(m.get('Column7') or m.get('score') or 0),
                "budget": pd.get("overall_budget", "-"),
                "status": pd.get("status", "-"),
                "objective": (pd.get("objective") or "")[:200] + "...",
                "decision": decision,
                "url": pd.get("url", "#")
            })
        
        projects.sort(key=lambda x: x['score'], reverse=True)
        
        # Resim Yolu Bulma (Düzeltildi)
        base_url = "https://estu-portal-backend.onrender.com"
        img_url = None
        
        # 1. Web Data'dan Bak
        for w in DB['WEB_DATA']:
            if w.get("Fullname") == name and w.get("Image_Path"):
                clean_path = w['Image_Path'].replace('\\', '/') # Windows slash düzeltme
                img_url = f"{base_url}/{clean_path}"
                break
        
        return JsonResponse({
            "profile": {
                "Fullname": acc.get("Fullname"),
                "Email": acc.get("Email"),
                "Title": acc.get("Title"),
                "Field": acc.get("Field"),
                "Image": img_url,
                "Duties": acc.get("Duties", [])
            },
            "projects": projects
        })
    except Exception as e: return JsonResponse({"error": str(e)}, 500)

# --- 6. RESİM VE STATİK DOSYA SUNUCUSU ---
def serve_file(request, folder, filename):
    """Dosyayı manuel olarak okuyup gönderir."""
    # Dosya yolunu oluştur
    file_path = os.path.join(BASE_DIR, folder, filename)
    
    # Dosya yoksa klasördeki dosyaları tara (Büyük/Küçük harf sorunu için)
    if not os.path.exists(file_path):
        found = False
        if os.path.exists(os.path.join(BASE_DIR, folder)):
            for f in os.listdir(os.path.join(BASE_DIR, folder)):
                if f.lower() == filename.lower():
                    file_path = os.path.join(BASE_DIR, folder, f)
                    found = True
                    break
        if not found:
            return HttpResponse(f"Dosya Bulunamadi: {folder}/{filename}", status=404)

    # Dosyayı sun
    try:
        mime_type, _ = mimetypes.guess_type(file_path)
        return FileResponse(open(file_path, 'rb'), content_type=mime_type)
    except Exception as e:
        return HttpResponse(f"Okuma Hatasi: {str(e)}", status=500)

# --- 7. URL YÖNLENDİRMELERİ ---
urlpatterns = [
    path('', index),
    path('api/login/', api_login),
    path('api/profile/', api_profile),
    
    # Resim Yolları (Hem images hem akademisyen_fotograflari için)
    path('images/<str:filename>', lambda r, filename: serve_file(r, 'images', filename)),
    path('akademisyen_fotograflari/<str:filename>', lambda r, filename: serve_file(r, 'akademisyen_fotograflari', filename)),
]

application = get_wsgi_application()

if __name__ == "__main__":
    execute_from_command_line(sys.argv)
