import os
import sys
import json
import mimetypes
import datetime
from collections import Counter
from django.conf import settings
from django.core.management import execute_from_command_line
from django.core.wsgi import get_wsgi_application
from django.urls import path
from django.http import JsonResponse, HttpResponse, FileResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils.deprecation import MiddlewareMixin

# --- 1. DOSYA YOLLARI ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

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

# --- 2. MANUEL CORS MIDDLEWARE (GÜVENLİK KAPISINI AÇAN KOD) ---
class CorsMiddleware(MiddlewareMixin):
    def process_response(self, request, response):
        response["Access-Control-Allow-Origin"] = "*"
        response["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        response["Access-Control-Allow-Headers"] = "*"
        return response

# --- 3. DJANGO AYARLARI ---
if not settings.configured:
    settings.configure(
        DEBUG=True, # Hata ayıklama açık
        SECRET_KEY='gizli-anahtar-render-icin',
        ROOT_URLCONF=__name__,
        ALLOWED_HOSTS=['*'],
        INSTALLED_APPS=[
            'django.contrib.staticfiles',
            'django.contrib.contenttypes',
            'django.contrib.auth',
        ],
        MIDDLEWARE=[
            'app.CorsMiddleware', # <--- Bizim özel bekçi
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

def reload_db():
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

reload_db() # Başlangıçta yükle

# --- 5. YARDIMCI FONKSİYONLAR ---
def save_json(filepath, data):
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except: pass

def log_access(name, role, action):
    entry = {
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "name": name,
        "role": role,
        "action": action
    }
    DB['LOGS'].insert(0, entry) # En başa ekle
    save_json(FILES['logs'], DB['LOGS'])

# --- 6. API ENDPOINTLERİ ---

def index(request):
    return HttpResponse("Backend Calisiyor! (Full Surum)")

@csrf_exempt
def api_login(request):
    if request.method == "OPTIONS": return JsonResponse({})
    try:
        d = json.loads(request.body)
        u = d.get('username', '').lower().strip()
        p = d.get('password', '').strip()
        
        if u == "admin" and p == "12345":
            log_access("Yönetici", "admin", "Giriş Yaptı")
            return JsonResponse({"status": "success", "role": "admin", "name": "Yönetici"})
            
        if u in DB['ACADEMICIANS']:
            real_pass = DB['PASSWORDS'].get(u, u.split('@')[0])
            if p == real_pass:
                acc_name = DB['ACADEMICIANS'][u]["Fullname"]
                log_access(acc_name, "academician", "Giriş Yaptı")
                return JsonResponse({"status": "success", "role": "academician", "name": acc_name})
        
        return JsonResponse({"status": "error", "message": "Hatali giris"}, status=401)
    except: return JsonResponse({}, 400)

@csrf_exempt
def api_admin_data(request):
    """Admin panelindeki listeyi dolduran fonksiyon"""
    if request.method == "OPTIONS": return JsonResponse({})
    
    # Akademisyen Listesini Hazırla
    acc_list = []
    for email, acc in DB['ACADEMICIANS'].items():
        name = acc.get("Fullname")
        
        # Proje Sayısı ve En İyi Skor
        my_matches = [m for m in DB['MATCHES'] if isinstance(m, dict) and (m.get('data') == name or m.get('academician_name') == name)]
        best_score = 0
        for m in my_matches:
            try:
                s = int(m.get('Column7') or m.get('score') or 0)
                if s > best_score: best_score = s
            except: pass
            
        # Resim Yolu
        img = None
        for w in DB['WEB_DATA']:
            if w.get("Fullname") == name and w.get("Image_Path"):
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
        
        acc = None
        for email, p in DB['ACADEMICIANS'].items():
            if p.get("Fullname") == name:
                acc = p
                break
        
        if not acc: return JsonResponse({"error": "Bulunamadi"}, 404)

        my_matches = [m for m in DB['MATCHES'] if isinstance(m, dict) and (m.get('data') == name or m.get('academician_name') == name)]
        
        projects = []
        for m in my_matches:
            pid = str(m.get('Column3') or m.get('project_id') or "")
            pd = DB['PROJECTS'].get(pid, {})
            title = pd.get("title") or pd.get("acronym") or f"Proje-{pid}"
            
            decision = "waiting"
            rating = 0
            note = ""
            for fb in DB['FEEDBACK']:
                if fb.get("academician") == name and fb.get("projId") == pid:
                    decision = fb.get("decision")
                    rating = fb.get("rating", 0)
                    note = fb.get("note", "")
                    break
            
            # İşbirlikçiler (Diğer kabul eden hocalar)
            collaborators = []
            for fb in DB['FEEDBACK']:
                if fb.get("projId") == pid and fb.get("decision") == "accepted" and fb.get("academician") != name:
                    collaborators.append(fb.get("academician"))

            projects.append({
                "id": pid,
                "title": title,
                "score": int(m.get('Column7') or m.get('score') or 0),
                "budget": pd.get("overall_budget", "-"),
                "status": pd.get("status", "-"),
                "objective": (pd.get("objective") or "")[:300] + "...",
                "decision": decision,
                "rating": rating,
                "note": note,
                "collaborators": collaborators,
                "url": pd.get("url", "#")
            })
        
        projects.sort(key=lambda x: x['score'], reverse=True)
        
        base_url = "https://estu-portal-backend.onrender.com"
        img_url = None
        for w in DB['WEB_DATA']:
            if w.get("Fullname") == name and w.get("Image_Path"):
                img_url = f"{base_url}/{w['Image_Path'].replace('\\', '/')}"
                break
        
        return JsonResponse({
            "profile": {
                "Fullname": acc.get("Fullname"),
                "Email": acc.get("Email"),
                "Title": acc.get("Title"),
                "Field": acc.get("Field"),
                "Image": img_url,
                "Duties": acc.get("Duties", []),
                "Phone": acc.get("Phone", "-")
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
        
        found = False
        for item in DB['FEEDBACK']:
            if item["academician"] == acc and item["projId"] == pid:
                item.update(d)
                found = True
                break
        if not found: DB['FEEDBACK'].append(d)
            
        save_json(FILES['decisions'], DB['FEEDBACK'])
        return JsonResponse({"status": "success"})
    except: return JsonResponse({}, 400)

@csrf_exempt
def api_top_projects(request):
    if request.method == "OPTIONS": return JsonResponse({})
    cnt = Counter(m.get('Column3') or m.get('project_id') for m in DB['MATCHES'] if isinstance(m, dict)).most_common(50)
    top = []
    for pid, c in cnt:
        if not pid: continue
        pd = DB['PROJECTS'].get(str(pid), {})
        top.append({
            "id": pid,
            "count": c,
            "title": pd.get("title") or pd.get("acronym") or f"Proje-{pid}",
            "budget": pd.get("overall_budget", "-"),
            "status": pd.get("status", "-"),
            "url": pd.get("url", "#")
        })
    return JsonResponse(top, safe=False)

@csrf_exempt
def api_announcements(request):
    if request.method == "OPTIONS": return JsonResponse({})
    if request.method == "GET":
        return JsonResponse(DB['ANNOUNCEMENTS'], safe=False)
    elif request.method == "POST":
        d = json.loads(request.body)
        if d.get("action") == "delete":
            try:
                del DB['ANNOUNCEMENTS'][d["index"]]
                save_json(FILES['announcements'], DB['ANNOUNCEMENTS'])
            except: pass
        else:
            d["date"] = datetime.datetime.now().strftime("%d.%m.%Y")
            DB['ANNOUNCEMENTS'].insert(0, d)
            save_json(FILES['announcements'], DB['ANNOUNCEMENTS'])
        return JsonResponse({"status": "success"})

@csrf_exempt
def api_messages(request):
    if request.method == "OPTIONS": return JsonResponse({})
    try:
        d = json.loads(request.body)
        if d.get("action") == "send":
            msg = {
                "id": len(DB['MESSAGES']) + 1,
                "sender": d.get("sender"),
                "receiver": d.get("receiver"),
                "content": d.get("content"),
                "timestamp": datetime.datetime.now().strftime("%d.%m.%Y %H:%M:%S")
            }
            DB['MESSAGES'].append(msg)
            save_json(FILES['messages'], DB['MESSAGES'])
            return JsonResponse({"status": "success"})
        else:
            # Listeleme
            return JsonResponse(DB['MESSAGES'], safe=False)
    except: return JsonResponse([], safe=False)

@csrf_exempt
def api_network_graph(request):
    """Network graph verisi"""
    if request.method == "OPTIONS": return JsonResponse({})
    user = request.GET.get('user')
    nodes = [{"id": user, "group": 1, "isCenter": True, "img": ""}]
    links = []
    
    # Kullanıcının kabul ettiği projeler
    my_projects = set()
    for fb in DB['FEEDBACK']:
        if fb.get("academician") == user and fb.get("decision") == "accepted":
            my_projects.add(fb.get("projId"))
            
    # Ortak proje paydaşları
    collaborators = set()
    for fb in DB['FEEDBACK']:
        if fb.get("projId") in my_projects and fb.get("decision") == "accepted" and fb.get("academician") != user:
            collaborators.add(fb.get("academician"))
            
    for col in collaborators:
        # Ortak resmi bul
        img = ""
        for w in DB['WEB_DATA']:
            if w.get("Fullname") == col:
                img = w.get("Image_Path", "").replace('\\', '/')
                break
        
        nodes.append({"id": col, "group": 2, "img": img})
        links.append({"source": user, "target": col})
        
    return JsonResponse({"nodes": nodes, "links": links})

def serve_file(request, folder, filename):
    file_path = os.path.join(BASE_DIR, folder, filename)
    if not os.path.exists(file_path):
        if os.path.exists(os.path.join(BASE_DIR, folder)):
            for f in os.listdir(os.path.join(BASE_DIR, folder)):
                if f.lower() == filename.lower():
                    return FileResponse(open(os.path.join(BASE_DIR, folder, f), 'rb'))
        return HttpResponse("Yok", status=404)
    return FileResponse(open(file_path, 'rb'))

# --- 7. URL YÖNLENDİRMELERİ ---
urlpatterns = [
    path('', index),
    path('api/login/', api_login),
    path('api/admin-data/', api_admin_data), # <-- BU EKSİKTİ, EKLENDİ!
    path('api/profile/', api_profile),
    path('api/decision/', api_project_decision),
    path('api/top-projects/', api_top_projects),
    path('api/announcements/', api_announcements),
    path('api/messages/', api_messages),
    path('api/network-graph/', api_network_graph),
    
    path('images/<str:filename>', lambda r, filename: serve_file(r, 'images', filename)),
    path('akademisyen_fotograflari/<str:filename>', lambda r, filename: serve_file(r, 'akademisyen_fotograflari', filename)),
]

application = get_wsgi_application()

if __name__ == "__main__":
    execute_from_command_line(sys.argv)
