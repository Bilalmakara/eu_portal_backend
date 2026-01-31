import os
import sys
import json
import mimetypes
import datetime
import unicodedata
from collections import Counter
from django.conf import settings
from django.core.management import execute_from_command_line
from django.core.wsgi import get_wsgi_application
from django.urls import path
from django.http import JsonResponse, HttpResponse, FileResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils.deprecation import MiddlewareMixin

# --- 1. AYARLAR ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Dosya İsimleri (Kod bunları otomatik arayıp bulacak)
TARGET_FILES = {
    'decisions': 'decisions.json',
    'matches': 'n8n_akademisyen_proje_onerileri.json',
    'projects': 'eu_projects_merged_tum.json',
    'academicians': 'academicians_merged.json',
    'web_data': 'web_data.json',
    'messages': 'messages.json',
    'announcements': 'announcements.json',
    'logs': 'access_logs.json',
    'passwords': 'passwords.json'
}

# --- 2. MANUEL CORS MIDDLEWARE ---
class CorsMiddleware(MiddlewareMixin):
    def process_response(self, request, response):
        response["Access-Control-Allow-Origin"] = "*"
        response["Access-Control-Allow-Methods"] = "*"
        response["Access-Control-Allow-Headers"] = "*"
        return response

# --- 3. DJANGO AYARLARI ---
if not settings.configured:
    settings.configure(
        DEBUG=True,
        SECRET_KEY='gizli-anahtar',
        ROOT_URLCONF=__name__,
        ALLOWED_HOSTS=['*'],
        INSTALLED_APPS=['django.contrib.staticfiles','django.contrib.contenttypes','django.contrib.auth'],
        MIDDLEWARE=['app.CorsMiddleware','django.middleware.common.CommonMiddleware'],
    )

# --- 4. AKILLI VERİ YÜKLEME ---
DB = {}

def normalize_name(name):
    """İsim eşleştirmesi için Türkçe karakterleri ve boşlukları temizler"""
    if not name: return ""
    return unicodedata.normalize('NFKD', str(name)).encode('ASCII', 'ignore').decode('utf-8').upper().strip()

def find_file(filename):
    """Büyük/Küçük harf duyarlılığı olmadan dosyayı bulur"""
    exact_path = os.path.join(BASE_DIR, filename)
    if os.path.exists(exact_path): return exact_path
    
    # Bulamazsa klasörü tara
    for f in os.listdir(BASE_DIR):
        if f.lower() == filename.lower():
            return os.path.join(BASE_DIR, f)
    return None

def load_data():
    global DB
    temp_db = { 'PROJECTS': {}, 'ACADEMICIANS': {}, 'MATCHES': [], 'FEEDBACK': [], 'WEB_DATA': [], 'MESSAGES': [], 'ANNOUNCEMENTS': [], 'LOGS': [], 'PASSWORDS': {} }
    
    # 1. Dosyaları Yükle
    for key, filename in TARGET_FILES.items():
        path = find_file(filename)
        data_key = key.upper()
        if key == 'matches': data_key = 'MATCHES'
        
        if path:
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if key == 'passwords': temp_db['PASSWORDS'] = data
                    elif key == 'projects':
                        # Projeleri ID'ye göre sözlük yap
                        raw = data if isinstance(data, list) else []
                        if isinstance(data, dict): raw = data.values() # Eğer dict gelirse
                        for p in raw:
                            pid = str(p.get("project_id", "")).strip()
                            if pid: temp_db['PROJECTS'][pid] = p
                    elif key == 'academicians':
                        # Akademisyenleri Email'e göre sözlük yap
                        for p in data:
                            if p.get("Email"): temp_db['ACADEMICIANS'][p["Email"].strip().lower()] = p
                    else:
                        temp_db[data_key] = data
            except Exception as e:
                print(f"HATA - {filename}: {e}")
    
    DB = temp_db

load_data()

# --- 5. API ENDPOINTLERİ ---

def index(request):
    return HttpResponse("Backend Calisiyor. Veri durumunu gormek icin: /api/test/ adresine git.")

@csrf_exempt
def api_test_data(request):
    """Verilerin yüklenip yüklenmediğini kontrol eden ekran"""
    status = {k: len(v) for k, v in DB.items()}
    status['FILE_PATHS'] = {k: find_file(v) for k, v in TARGET_FILES.items()}
    return JsonResponse(status, json_dumps_params={'indent': 4})

@csrf_exempt
def api_login(request):
    if request.method == "OPTIONS": return JsonResponse({})
    try:
        d = json.loads(request.body)
        u = d.get('username', '').lower().strip()
        p = d.get('password', '').strip()
        
        if u == "admin" and p == "12345":
            return JsonResponse({"status": "success", "role": "admin", "name": "Yönetici"})
            
        if u in DB['ACADEMICIANS']:
            real_pass = DB['PASSWORDS'].get(u, u.split('@')[0])
            if p == real_pass:
                acc = DB['ACADEMICIANS'][u]
                return JsonResponse({"status": "success", "role": "academician", "name": acc["Fullname"]})
        
        return JsonResponse({"status": "error", "message": "Hatali giris"}, status=401)
    except: return JsonResponse({}, 400)

@csrf_exempt
def api_admin_data(request):
    if request.method == "OPTIONS": return JsonResponse({})
    
    acc_list = []
    # Eşleşme verisini normalize et (Hızlandırmak için)
    matches_map = {} # İsim -> Sayı
    
    # MATCHES listesini analiz et
    for m in DB['MATCHES']:
        # Olası isim alanları (n8n çıktısına göre değişebilir)
        raw_name = m.get('data') or m.get('academician_name') or m.get('Column1')
        if raw_name:
            norm = normalize_name(raw_name)
            if norm not in matches_map: matches_map[norm] = []
            matches_map[norm].append(m)

    for email, acc in DB['ACADEMICIANS'].items():
        name = acc.get("Fullname", "")
        norm_name = normalize_name(name)
        
        # Eşleşmeleri bul
        my_matches = matches_map.get(norm_name, [])
        
        # En iyi skoru bul
        best_score = 0
        for m in my_matches:
            try:
                s = int(m.get('Column7') or m.get('score') or 0)
                if s > best_score: best_score = s
            except: pass
            
        # Resim bul (Web Data'dan)
        img = None
        for w in DB['WEB_DATA']:
            if normalize_name(w.get("Fullname")) == norm_name and w.get("Image_Path"):
                img = w['Image_Path'].replace('\\', '/')
                break
        
        acc_list.append({
            "name": name,
            "email": email,
            "project_count": len(my_matches),
            "best_score": best_score,
            "image": img
        })
    
    return JsonResponse({
        "academicians": acc_list,
        "feedbacks": DB['FEEDBACK'],
        "logs": DB['LOGS'],
        "announcements": DB['ANNOUNCEMENTS']
    })

@csrf_exempt
def api_profile(request):
    if request.method == "OPTIONS": return JsonResponse({})
    try:
        body = json.loads(request.body)
        name = body.get('name')
        norm_name = normalize_name(name)
        
        acc = None
        for email, p in DB['ACADEMICIANS'].items():
            if normalize_name(p.get("Fullname")) == norm_name:
                acc = p
                break
        if not acc: return JsonResponse({"error": "Bulunamadi"}, 404)

        # Projeleri Bul
        projects = []
        for m in DB['MATCHES']:
            m_name = m.get('data') or m.get('academician_name')
            if normalize_name(m_name) == norm_name:
                pid = str(m.get('Column3') or m.get('project_id') or "")
                pd = DB['PROJECTS'].get(pid, {})
                
                decision = "waiting"
                for fb in DB['FEEDBACK']:
                    if normalize_name(fb.get("academician")) == norm_name and str(fb.get("projId")) == pid:
                        decision = fb.get("decision")
                        break
                
                projects.append({
                    "id": pid,
                    "title": pd.get("title") or pd.get("acronym") or f"Proje-{pid}",
                    "score": int(m.get('Column7') or m.get('score') or 0),
                    "budget": pd.get("overall_budget", "-"),
                    "status": pd.get("status", "-"),
                    "objective": (pd.get("objective") or "")[:200] + "...",
                    "decision": decision,
                    "url": pd.get("url", "#")
                })
        
        projects.sort(key=lambda x: x['score'], reverse=True)
        
        img_url = None
        base_url = "https://estu-portal-backend.onrender.com"
        for w in DB['WEB_DATA']:
            if normalize_name(w.get("Fullname")) == norm_name and w.get("Image_Path"):
                img_url = f"{base_url}/{w['Image_Path'].replace('\\', '/')}"
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

@csrf_exempt
def api_project_decision(request):
    if request.method == "OPTIONS": return JsonResponse({})
    try:
        d = json.loads(request.body)
        acc = d.get("academician")
        pid = d.get("projId")
        # Basit ekleme
        DB['FEEDBACK'].append(d)
        with open(os.path.join(BASE_DIR, 'decisions.json'), 'w') as f:
            json.dump(DB['FEEDBACK'], f)
        return JsonResponse({"status": "success"})
    except: return JsonResponse({}, 400)

@csrf_exempt
def api_top_projects(request):
    if request.method == "OPTIONS": return JsonResponse({})
    # Basit Top Projects
    cnt = Counter()
    for m in DB['MATCHES']:
        pid = m.get('Column3') or m.get('project_id')
        if pid: cnt[str(pid)] += 1
    
    top = []
    for pid, c in cnt.most_common(50):
        pd = DB['PROJECTS'].get(pid, {})
        top.append({
            "id": pid,
            "count": c,
            "title": pd.get("title") or f"Proje-{pid}",
            "budget": pd.get("overall_budget", "-"),
            "status": pd.get("status", "-"),
            "url": pd.get("url", "#")
        })
    return JsonResponse(top, safe=False)

@csrf_exempt
def api_announcements(request):
    if request.method == "OPTIONS": return JsonResponse({})
    if request.method == "POST":
        d = json.loads(request.body)
        if d.get("action") == "delete":
            try: del DB['ANNOUNCEMENTS'][d["index"]]
            except: pass
        else:
            d["date"] = datetime.datetime.now().strftime("%d.%m.%Y")
            DB['ANNOUNCEMENTS'].insert(0, d)
        return JsonResponse({"status": "success"})
    return JsonResponse(DB['ANNOUNCEMENTS'], safe=False)

@csrf_exempt
def api_messages(request):
    if request.method == "OPTIONS": return JsonResponse({})
    if request.method == "POST":
        try:
            d = json.loads(request.body)
            if d.get("action") == "list": return JsonResponse(DB['MESSAGES'], safe=False)
            if d.get("action") == "send":
                d['timestamp'] = datetime.datetime.now().strftime("%d.%m.%Y %H:%M:%S")
                DB['MESSAGES'].append(d)
                return JsonResponse({"status": "success"})
        except: pass
    return JsonResponse([], safe=False)

def serve_file(request, folder, filename):
    # Klasör içini tara ve dosyayı bul (Büyük/Küçük harf duyarsız)
    folder_path = os.path.join(BASE_DIR, folder)
    if os.path.exists(folder_path):
        for f in os.listdir(folder_path):
            if f.lower() == filename.lower():
                return FileResponse(open(os.path.join(folder_path, f), 'rb'))
    return HttpResponse("Yok", status=404)

urlpatterns = [
    path('', index),
    path('api/test/', api_test_data), # <-- TEST İÇİN BUNU EKLEDİM
    path('api/login/', api_login),
    path('api/admin-data/', api_admin_data),
    path('api/profile/', api_profile),
    path('api/decision/', api_project_decision),
    path('api/top-projects/', api_top_projects),
    path('api/announcements/', api_announcements),
    path('api/messages/', api_messages),
    path('images/<str:filename>', lambda r, filename: serve_file(r, 'images', filename)),
    path('akademisyen_fotograflari/<str:filename>', lambda r, filename: serve_file(r, 'akademisyen_fotograflari', filename)),
]

application = get_wsgi_application()

if __name__ == "__main__":
    execute_from_command_line(sys.argv)
