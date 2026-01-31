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

# Dosya İsimleri
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
        SECRET_KEY='gizli-anahtar-render-icin',
        ROOT_URLCONF=__name__,
        ALLOWED_HOSTS=['*'],
        INSTALLED_APPS=['django.contrib.staticfiles','django.contrib.contenttypes','django.contrib.auth'],
        MIDDLEWARE=['app.CorsMiddleware','django.middleware.common.CommonMiddleware'],
    )

# --- 4. AKILLI VERİ YÜKLEME ---
DB = {}

def normalize_name(name):
    """Türkçe karakter ve boşluk temizliği"""
    if not name: return ""
    return unicodedata.normalize('NFKD', str(name)).encode('ASCII', 'ignore').decode('utf-8').upper().strip()

def find_file(filename):
    """Dosyayı bul (Büyük/Küçük harf duyarsız)"""
    exact_path = os.path.join(BASE_DIR, filename)
    if os.path.exists(exact_path): return exact_path
    for f in os.listdir(BASE_DIR):
        if f.lower() == filename.lower():
            return os.path.join(BASE_DIR, f)
    return None

def load_data():
    global DB
    temp_db = { 'PROJECTS': {}, 'ACADEMICIANS': {}, 'MATCHES': [], 'FEEDBACK': [], 'WEB_DATA': [], 'MESSAGES': [], 'ANNOUNCEMENTS': [], 'LOGS': [], 'PASSWORDS': {} }
    
    for key, filename in TARGET_FILES.items():
        path = find_file(filename)
        
        if path:
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    
                    # --- 1. EŞLEŞMELERİ DÜZELT (FORWARD FILL) ---
                    if key == 'matches':
                        raw_list = []
                        if isinstance(data, dict):
                            for k, v in data.items():
                                if isinstance(v, list):
                                    raw_list = v
                                    break
                        elif isinstance(data, list):
                            raw_list = data
                        
                        clean_matches = []
                        last_valid_name = None
                        for item in raw_list:
                            raw_name = item.get('data') or item.get('academician_name')
                            if raw_name: last_valid_name = raw_name
                            current_name = raw_name if raw_name else last_valid_name

                            pid = str(item.get('Column3') or item.get('project_id') or "")
                            if not current_name or not pid: continue
                            if current_name in ["academician_name", "data", "Sheet1"]: continue
                            if pid in ["matches", "project_id", "Column3"]: continue
                            
                            item['data'] = current_name 
                            clean_matches.append(item)
                        temp_db['MATCHES'] = clean_matches

                    # --- 2. PROJELERİ SÖZLÜK YAP ---
                    elif key == 'projects':
                        raw = data if isinstance(data, list) else (data.values() if isinstance(data, dict) else [])
                        for p in raw:
                            pid = str(p.get("project_id", "")).strip()
                            if pid: temp_db['PROJECTS'][pid] = p

                    # --- 3. AKADEMİSYENLERİ SÖZLÜK YAP ---
                    elif key == 'academicians':
                        for p in data:
                            if p.get("Email"): temp_db['ACADEMICIANS'][p["Email"].strip().lower()] = p
                    
                    # --- 4. KARARLARI (FEEDBACK) YÜKLE (ÇOK ÖNEMLİ!) ---
                    elif key == 'decisions':
                        temp_db['FEEDBACK'] = data # Hata buradaydı, düzeltildi.
                    
                    # --- 5. DİĞERLERİNİ NORMAL YÜKLE ---
                    else:
                        temp_db[key.upper()] = data
            except Exception as e:
                print(f"HATA - {filename}: {e}")
    
    DB = temp_db

load_data()

def get_image_url_for_name(name):
    """
    Akademisyen ismine göre web_data.json'dan Image_Path bilgisini çeker
    ve GitHub RAW linki döner (Render bağımsız).
    """
    norm_name = normalize_name(name)

    GITHUB_RAW_BASE = (
        "https://raw.githubusercontent.com/"
        "Bilalmakara/eu-portal-backend/main"
    )

    for w in DB['WEB_DATA']:
        if normalize_name(w.get("Fullname")) == norm_name:
            path_val = w.get("Image_Path")
            if path_val:
                filename = path_val.replace('\\', '/').split('/')[-1]
                return f"{GITHUB_RAW_BASE}/akademisyen_fotograflari/{filename}"

    return None

    
# --- 5. API ENDPOINTLERİ ---

def index(request):
    return HttpResponse("Backend Calisiyor. Test: /api/test/")

@csrf_exempt
def api_debug_images(request):
    """Resim klasöründe ne var ne yok gösteren teşhis fonksiyonu"""
    debug_info = {
        "BASE_DIR": BASE_DIR,
        "FOLDERS_IN_BASE": [f for f in os.listdir(BASE_DIR) if os.path.isdir(os.path.join(BASE_DIR, f))],
        "TARGET_FOLDER_SEARCH": "akademisyen_fotograflari",
        "FOUND_FILES": []
    }
    
    # Klasörü bulmaya çalış
    found_path = None
    for f in os.listdir(BASE_DIR):
        if f.lower() == "akademisyen_fotograflari":
            found_path = os.path.join(BASE_DIR, f)
            debug_info["MATCHED_FOLDER_NAME"] = f
            break
            
    if found_path:
        # İçindeki ilk 20 dosyayı listele
        files = os.listdir(found_path)
        debug_info["TOTAL_FILE_COUNT"] = len(files)
        debug_info["FIRST_20_FILES"] = files[:20]
    else:
        debug_info["ERROR"] = "Klasor sunucuda hic bulunamadi!"
        
    return JsonResponse(debug_info, json_dumps_params={'indent': 4})
    
@csrf_exempt
def api_test_data(request):
    status = {k: len(v) for k, v in DB.items()}
    status['FILE_PATHS'] = {k: find_file(v) for k, v in TARGET_FILES.items()}
    # Hata ayıklama için ilk 1 eşleşmeyi göster
    if len(DB['MATCHES']) > 0:
        status['SAMPLE_MATCH'] = DB['MATCHES'][0]
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
    # Hızlı eşleşme sayımı için map oluştur
    matches_map = {} 
    
    for m in DB['MATCHES']:
        raw_name = m.get('data') or m.get('academician_name')
        if raw_name:
            norm = normalize_name(raw_name)
            if norm not in matches_map: matches_map[norm] = []
            matches_map[norm].append(m)

    for email, acc in DB['ACADEMICIANS'].items():
        name = acc.get("Fullname", "")
        norm_name = normalize_name(name)
        
        my_matches = matches_map.get(norm_name, [])
        best_score = 0
        for m in my_matches:
            try:
                s = int(m.get('Column7') or m.get('score') or 0)
                if s > best_score: best_score = s
            except: pass
            
        image = get_image_url_for_name(name)
        
        acc_list.append({
            "name": name,
            "email": email,
            "project_count": len(my_matches),
            "best_score": best_score,
            "image": image  # <-- BURAYI GÜNCELLE
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

        projects = []
        for m in DB['MATCHES']:
            m_name = m.get('data') or m.get('academician_name')
            if normalize_name(m_name) == norm_name:
                pid = str(m.get('Column3') or m.get('project_id') or "")
                pd = DB['PROJECTS'].get(pid, {})
                
                decision = "waiting"
                # FEEDBACK listesinde ara
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
        
        img_url = get_image_url_for_name(name)
        
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
        DB['FEEDBACK'].append(d)
        with open(os.path.join(BASE_DIR, 'decisions.json'), 'w') as f:
            json.dump(DB['FEEDBACK'], f)
        return JsonResponse({"status": "success"})
    except: return JsonResponse({}, 400)

@csrf_exempt
def api_top_projects(request):
    if request.method == "OPTIONS": return JsonResponse({})
    
    # Eşleşmeleri Say
    cnt = Counter()
    for m in DB['MATCHES']:
        pid = str(m.get('Column3') or m.get('project_id') or "").strip()
        if pid: cnt[pid] += 1
    
    top = []
    for pid, c in cnt.most_common(50):
        # Proje detayını bul
        pd = DB['PROJECTS'].get(pid, {})
        
        # Başlık Bulma (Sırasıyla dene: title -> acronym -> ID)
        title = pd.get("title")
        if not title: title = pd.get("acronym")
        if not title: title = pd.get("project_acronym")
        if not title: title = f"Proje-{pid}" # Hiçbiri yoksa ID yaz
        
        top.append({
            "id": pid,
            "count": c,
            "title": title,
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

@csrf_exempt
def api_network_graph(request):
    """Kişisel İşbirliği Ağı: Aynı projeyi kabul eden hocaları bağlar"""
    if request.method == "OPTIONS": return JsonResponse({})
    
    user = request.GET.get('user') # İstek atan hoca
    if not user: return JsonResponse({"nodes": [], "links": []})

    norm_user = normalize_name(user)
    
    # 1. Merkez Düğüm (Kullanıcı)
    nodes = [{"id": user, "group": 1, "isCenter": True, "img": ""}]
    links = []
    added_nodes = {norm_user} # Eklenenleri takip et
    
    # 2. Kullanıcının KABUL ETTİĞİ projeleri bul
    my_accepted_projects = set()
    for fb in DB['FEEDBACK']:
        if normalize_name(fb.get("academician")) == norm_user and fb.get("decision") == "accepted":
            my_accepted_projects.add(str(fb.get("projId")))
            
    # 3. Bu projeleri BAŞKA kimler kabul etmiş?
    collaborators = set()
    for fb in DB['FEEDBACK']:
        p_id = str(fb.get("projId"))
        p_acc_norm = normalize_name(fb.get("academician"))
        
        # Eğer proje benim kabul ettiklerimden biriyse VE kişi ben değilsem VE o da kabul ettiyse
        if p_id in my_accepted_projects and p_acc_norm != norm_user and fb.get("decision") == "accepted":
            collaborators.add(fb.get("academician")) # Orijinal ismi ekle
            
    # 4. Ortakları Grafiğe Ekle
    base_url = "https://eu-portal-backend.onrender.com"
    
    for col_name in collaborators:
        norm_col = normalize_name(col_name)
        if norm_col in added_nodes: continue
        
        # Resim Bul
        img_url = get_image_url_for_name(col_name) # <-- Tek satırda halleder
        
        nodes.append({"id": col_name, "group": 2, "img": img_url})
        links.append({"source": user, "target": col_name})
        added_nodes.add(norm_col)
        
    return JsonResponse({"nodes": nodes, "links": links})

def serve_file(request, folder, filename):
    """
    Hem klasörü hem de dosyayı büyük/küçük harf duyarlılığı olmadan bulur.
    """
    # 1. Klasör İsmini Doğru Bul (Linux Uyumluluğu)
    target_folder_name = folder.lower()
    found_folder_path = None
    
    # Ana dizindeki klasörleri tara
    if os.path.exists(os.path.join(BASE_DIR, folder)):
        found_folder_path = os.path.join(BASE_DIR, folder)
    else:
        # Klasör bulunamadıysa, dizindeki tüm klasörlere bak (büyük/küçük harf eşleştir)
        for f in os.listdir(BASE_DIR):
            if os.path.isdir(os.path.join(BASE_DIR, f)):
                if f.lower() == target_folder_name:
                    found_folder_path = os.path.join(BASE_DIR, f)
                    break
    
    if not found_folder_path:
        return HttpResponse(f"Sunucuda '{folder}' adinda bir klasor bulunamadi. Lutfen GitHub'a yuklendiginden emin olun.", status=404)

    # 2. Dosya İsmini Doğru Bul
    target_filename = filename.lower()
    for f in os.listdir(found_folder_path):
        if f.lower() == target_filename:
            return FileResponse(open(os.path.join(found_folder_path, f), 'rb'))

    return HttpResponse(f"Dosya yok: {filename} (Klasor: {os.path.basename(found_folder_path)})", status=404)

urlpatterns = [
    path('', index),
    path('api/test/', api_test_data),
    path('api/login/', api_login),
    path('api/admin-data/', api_admin_data),
    path('api/profile/', api_profile),
    path('api/decision/', api_project_decision),
    path('api/top-projects/', api_top_projects),
    path('api/announcements/', api_announcements),
    path('api/messages/', api_messages),
    path('api/network-graph/', api_network_graph),
    path('images/<str:filename>', lambda r, filename: serve_file(r, 'images', filename)),
    path('akademisyen_fotograflari/<str:filename>', lambda r, filename: serve_file(r, 'akademisyen_fotograflari', filename)),
    path('api/debug-images/', api_debug_images), # <-- BUNU EKLE
]

application = get_wsgi_application()

if __name__ == "__main__":
    execute_from_command_line(sys.argv)
