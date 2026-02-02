import os
import sys
import json
import mimetypes
import datetime
import unicodedata
import re
from collections import Counter
from django.conf import settings
from django.core.management import execute_from_command_line
from django.core.wsgi import get_wsgi_application
from django.urls import path
from django.http import JsonResponse, HttpResponse, FileResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils.deprecation import MiddlewareMixin

# ==========================================
# 1. AYARLAR VE SABİTLER
# ==========================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Frontend'in resimleri çekebilmesi için Backend URL'i
BASE_URL = "https://eu-portal-backend.onrender.com"

# Dosya İsimleri (Kod bunları klasörde arayıp bulacak)
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


# ==========================================
# 2. GÜVENLİK VE CORS AYARLARI
# ==========================================
# --- 2. CORS MIDDLEWARE (GÜÇLENDİRİLMİŞ) ---
class CorsMiddleware(MiddlewareMixin):
    def process_request(self, request):
        # Preflight (OPTIONS) istekleri gelirse hemen 200 OK dön ve izin ver
        if request.method == "OPTIONS":
            response = HttpResponse()
            response["Access-Control-Allow-Origin"] = "*"
            response["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
            response["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Requested-With"
            return response
        return None

    def process_response(self, request, response):
        response["Access-Control-Allow-Origin"] = "*"
        response["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        response["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Requested-With"
        return response


if not settings.configured:
    settings.configure(
        DEBUG=True,
        SECRET_KEY='gizli-anahtar-render-icin-ozel',
        ROOT_URLCONF=__name__,
        ALLOWED_HOSTS=['*'],
        INSTALLED_APPS=[
            'django.contrib.staticfiles',
            'django.contrib.contenttypes',
            'django.contrib.auth',
        ],
        MIDDLEWARE=[
            'app.CorsMiddleware',
            'django.middleware.common.CommonMiddleware',
        ],
    )

# ==========================================
# 3. YARDIMCI FONKSİYONLAR
# ==========================================
DB = {}


def normalize_name(name):
    """
    İsim eşleştirmesi için temizlik yapar.
    'Prof. Dr. Ahmet Şen' -> 'AHMET SEN'
    """
    if not name: return ""
    n = str(name).strip().upper()
    # Ünvanları temizle
    n = n.replace("PROF.", "").replace("DR.", "").replace("ARS.", "").replace("GOR.", "").replace("DOC.", "")
    # Türkçe karakterleri İngilizceye çevir
    n = n.replace('İ', 'I').replace('Ğ', 'G').replace('Ü', 'U').replace('Ş', 'S').replace('Ö', 'O').replace('Ç', 'C')
    # Fazla boşlukları sil
    return " ".join(n.split())


def slugify_name(name):
    """
    Dosya isminden resim bulmak için (Fallback).
    'Uğur Özdemir' -> 'ugurozdemir'
    """
    if not name: return ""
    n = str(name).lower()
    n = n.replace('ğ', 'g').replace('ü', 'u').replace('ş', 's').replace('ı', 'i').replace('ö', 'o').replace('ç', 'c')
    # Sadece harf ve rakamları bırak
    n = re.sub(r'[^a-z0-9]', '', n)
    return n

def log_system_access(user, role, action):
    """Sistem erişim kayıtlarını tutar ve dosyaya yazar"""
    entry = {
        "Saat": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "Kullanıcı": user,
        "Rol": role,
        "İşlem": action
    }
    # En yeni kayıt en üstte olsun
    DB['LOGS'].insert(0, entry)
    
    # Dosyaya kaydet
    path = find_file('access_logs.json')
    if not path: path = os.path.join(BASE_DIR, 'access_logs.json')
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(DB['LOGS'], f, indent=4, ensure_ascii=False)
    except: pass

def find_file(filename):
    """Klasördeki dosyayı büyük/küçük harf gözetmeksizin bulur"""
    exact_path = os.path.join(BASE_DIR, filename)
    if os.path.exists(exact_path): return exact_path

    for f in os.listdir(BASE_DIR):
        if f.lower() == filename.lower():
            return os.path.join(BASE_DIR, f)
    return None


# ==========================================
# 4. VERİ YÜKLEME (DATA LOADING) - FİNAL SÜRÜM
# ==========================================

def get_all_rows(data):
    """JSON içindeki veriyi ne olursa olsun listeye çevirir"""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        all_rows = []
        for key, value in data.items():
            if isinstance(value, list):
                all_rows.extend(value)
        return all_rows
    return []

def load_data():
    global DB
    temp_db = { 
        'PROJECTS': {}, 'ACADEMICIANS': {}, 'MATCHES': [], 
        'FEEDBACK': [], 'WEB_DATA': [], 'MESSAGES': [], 
        'ANNOUNCEMENTS': [], 'LOGS': [], 'PASSWORDS': {} 
    }
    
    for key, filename in TARGET_FILES.items():
        path = find_file(filename)
        data_key = key.upper()
        # Özel anahtar isimleri
        if key == 'matches': data_key = 'MATCHES'
        elif key == 'decisions': data_key = 'FEEDBACK'
        
        if path:
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    file_content = f.read().strip()
                    if not file_content: continue
                    raw_json = json.loads(file_content)
                    data_list = get_all_rows(raw_json)

                    if key == 'matches':
                        # ... (Buradaki kod aynı kalsın) ...
                        clean_matches = []
                        last_valid_name = None 
                        for item in data_list:
                            raw_name = item.get('data') or item.get('academician_name') or item.get('Column1')
                            if raw_name:
                                temp_check = str(raw_name).strip()
                                if len(temp_check) > 2 and temp_check.lower() not in ["academician_name", "data", "sheet1", "column1", "matches"]:
                                    last_valid_name = temp_check
                            current_name = raw_name if raw_name else last_valid_name
                            pid = str(item.get('Column3') or item.get('project_id') or "").strip()
                            if not current_name or not pid: continue
                            check_name = normalize_name(current_name)
                            if "COLUMN" in check_name or "SHEET" in check_name or "DATA" in check_name: continue
                            if pid.lower() in ["matches", "project_id", "column3", "column"]: continue
                            item['data'] = current_name 
                            clean_matches.append(item)
                        temp_db['MATCHES'] = clean_matches

                    elif key == 'projects':
                        for p in data_list:
                            pid = str(p.get("project_id", "")).strip()
                            if pid: temp_db['PROJECTS'][pid] = p

                    elif key == 'academicians':
                        for p in data_list:
                            if p.get("Email"): temp_db['ACADEMICIANS'][p["Email"].strip().lower()] = p
                    
                    elif key == 'passwords':
                        for item in data_list:
                            p_email = item.get('email') or item.get('Email') or item.get('username')
                            p_pass = item.get('password') or item.get('sifre') or item.get('Password')
                            if p_email and p_pass:
                                temp_db['PASSWORDS'][str(p_email).strip().lower()] = str(p_pass).strip()

                    # LİSTE OLMASINI GARANTİ EDELİM
                    elif key == 'logs':
                        temp_db['LOGS'] = data_list if isinstance(data_list, list) else []
                    elif key == 'messages':
                        temp_db['MESSAGES'] = data_list if isinstance(data_list, list) else []
                    
                    else:
                        temp_db[data_key] = data_list

            except Exception as e:
                print(f"HATA - {filename}: {e}")
    
    DB = temp_db

# Uygulama başlarken yükle
load_data()

# ==========================================
# 5. RESİM BULUCU (IMAGE FINDER) - DÜZELTİLMİŞ (V4)
# ==========================================
def get_image_url_for_name(name):
    """
    Resim yolunu döndürür.
    DÜZELTME: Baştaki '/' işareti kaldırıldı.
    Böylece Frontend kendi slash'ini eklediğinde çift slash (//) hatası oluşmayacak.
    """
    norm_name = normalize_name(name)
    slug_name = slugify_name(name) 
    
    # 1. Yöntem: Web Data'dan
    for w in DB['WEB_DATA']:
        if normalize_name(w.get("Fullname")) == norm_name:
            path_val = w.get("Image_Path")
            if path_val:
                filename = path_val.replace('\\', '/').split('/')[-1]
                # Başına '/' koymadan dönüyoruz
                return f"akademisyen_fotograflari/{filename}"
    
    # 2. Yöntem: Tahmin
    # Başına '/' koymadan dönüyoruz
    return f"akademisyen_fotograflari/{slug_name}.jpg"


# ==========================================
# 6. API ENDPOINTLERİ (VIEWS)
# ==========================================

def index(request):
    return HttpResponse("Backend V3.0 (Full Fix) Calisiyor. Test: /api/test/")


@csrf_exempt
def api_test_data(request):
    """Sistem sağlık kontrolü"""
    check_name = request.GET.get('name', '')
    status = {
        "DB_COUNTS": {k: len(v) for k, v in DB.items()},
        "SAMPLE_MATCH": DB['MATCHES'][0] if len(DB['MATCHES']) > 0 else "Veri Yok",
    }
    if check_name:
        status['NAME_CHECK'] = {
            "Input": check_name,
            "Normalized": normalize_name(check_name),
            "Slugified": slugify_name(check_name),
            "Predicted_URL": get_image_url_for_name(check_name)
        }
    return JsonResponse(status, json_dumps_params={'indent': 4})


@csrf_exempt
def api_login(request):
    """Giriş İşlemleri (Loglama Özellikli)"""
    if request.method == "OPTIONS": return JsonResponse({})
    try:
        d = json.loads(request.body)
        u = d.get('username', '').lower().strip()
        p = d.get('password', '').strip()
        
        # 1. Admin Girişi
        if u == "admin" and p == "12345":
            log_system_access("Admin", "Yönetici", "Giriş Başarılı")
            return JsonResponse({"status": "success", "role": "admin", "name": "Yönetici"})
            
        # 2. Akademisyen Girişi
        if u in DB['ACADEMICIANS']:
            acc = DB['ACADEMICIANS'][u]
            # Şifre Kontrolü (Önce özel şifre, yoksa varsayılan)
            real_pass = DB['PASSWORDS'].get(u)
            if not real_pass: real_pass = u.split('@')[0]
            
            if str(p) == str(real_pass):
                log_system_access(acc.get("Fullname", u), "Akademisyen", "Giriş Başarılı")
                return JsonResponse({"status": "success", "role": "academician", "name": acc.get("Fullname")})
        
        # Hatalı Giriş
        log_system_access(u, "Bilinmiyor", "Hatalı Giriş Denemesi")
        return JsonResponse({"status": "error", "message": "Hatali giris"}, status=401)
    except Exception as e: 
        return JsonResponse({"error": str(e)}, 400)

@csrf_exempt
def api_change_password(request):
    """Şifre Değiştirme (Frontend: /api/change-password/)"""
    if request.method == "OPTIONS": return JsonResponse({})
    try:
        d = json.loads(request.body)
        # Frontend 'username' göndermiyorsa, token yapısı olmadığı için 
        # email'i body içinde göndermesi gerekir. 
        # Eğer göndermiyorsa bu basit sistemde pass.json'u güncelleyemeyiz.
        # Varsayım: Frontend email ve newPassword gönderiyor.
        
        u = d.get('username') or d.get('email', '').lower().strip()
        new_p = d.get('password') or d.get('newPassword', '').strip()
        
        if u and u in DB['ACADEMICIANS']:
            # 1. Hafızayı Güncelle
            DB['PASSWORDS'][u] = new_p
            
            # 2. Dosyayı Güncelle
            save_list = [{"email": email, "password": password} for email, password in DB['PASSWORDS'].items()]
            
            save_path = find_file('passwords.json')
            if not save_path: save_path = os.path.join(BASE_DIR, 'passwords.json')
            
            with open(save_path, 'w', encoding='utf-8') as f:
                json.dump(save_list, f, indent=4)
                
            return JsonResponse({"status": "success", "message": "Sifre degistirildi"})
            
        return JsonResponse({"status": "error", "message": "Kullanici bulunamadi"}, 404)
    except Exception as e: 
        return JsonResponse({"error": str(e)}, 500)

@csrf_exempt
def api_logout(request):
    """Çıkış İşlemi ve Loglama"""
    try:
        # Frontend'den kimin çıktığını öğrenmeye çalışıyoruz (varsa)
        # Genelde logout body'siz atılır ama basit bir log için varsayım yapıyoruz
        body = json.loads(request.body) if request.body else {}
        user = body.get('username') or "Kullanıcı"
        role = body.get('role') or "Belirsiz"
        
        log_system_access(user, role, "Çıkış Yapıldı")
    except:
        pass
    return JsonResponse({"status": "success", "message": "Cikis yapildi"})
        
@csrf_exempt
def api_admin_data(request):
    """Yönetici Paneli: Verileri temizleyerek gönderir (Crash Fix)"""
    if request.method == "OPTIONS": return JsonResponse({})
    
    # 1. Akademisyen Listesini Hazırla
    acc_list = []
    matches_map = {} 
    for m in DB.get('MATCHES', []):
        raw_name = m.get('data')
        if raw_name:
            norm = normalize_name(raw_name)
            if norm not in matches_map: matches_map[norm] = []
            matches_map[norm].append(m)

    for email, acc in DB['ACADEMICIANS'].items():
        name = acc.get("Fullname", "")
        # Resim yolu (Baştaki slash sorununu da çözen fonksiyonu kullanıyoruz)
        image_path = get_image_url_for_name(name)
        
        acc_list.append({
            "name": name,
            "email": email,
            "project_count": len(matches_map.get(normalize_name(name), [])),
            "best_score": 0, # İstersen hesaplayabilirsin ama hız için 0 kalsın
            "image": image_path 
        })
    
    # 2. LOGLARI TEMİZLE (Kritik Kısım)
    raw_logs = DB.get('LOGS', [])
    if not isinstance(raw_logs, list): raw_logs = []
    
    safe_logs = []
    for log in raw_logs:
        # Frontend'in beklediği alanlar: Saat, Kullanıcı, Rol, İşlem
        # Hepsi STRING olmak zorunda. Asla None gitmemeli.
        safe_logs.append({
            "Saat": str(log.get("Saat") or "-"),
            "Kullanıcı": str(log.get("Kullanıcı") or "Bilinmiyor"),
            "Rol": str(log.get("Rol") or "-"),
            "İşlem": str(log.get("İşlem") or "-")
        })
    
    # En yeni kayıt en üstte
    safe_logs.reverse()

    return JsonResponse({
        "academicians": acc_list,
        "feedbacks": DB.get('FEEDBACK', []),
        "logs": safe_logs, # Temizlenmiş loglar
        "announcements": DB.get('ANNOUNCEMENTS', [])
    })
    
    # --- KAYITLARI TEMİZLE (CRASH FIX) ---
    raw_logs = DB.get('LOGS', [])
    if not isinstance(raw_logs, list): raw_logs = []
    
    safe_logs = []
    for log in raw_logs:
        # Her alanı string'e çeviriyoruz. None ise "-" yapıyoruz.
        # Bu işlem frontend'deki .includes() hatasını %100 çözer.
        safe_entry = {
            "Saat": str(log.get("Saat") or "-"),
            "Kullanıcı": str(log.get("Kullanıcı") or "Bilinmiyor"),
            "Rol": str(log.get("Rol") or "-"),
            "İşlem": str(log.get("İşlem") or "-")
        }
        safe_logs.append(safe_entry)
    
    # En yeni en üstte olsun
    safe_logs.reverse()

    return JsonResponse({
        "academicians": acc_list,
        "feedbacks": DB.get('FEEDBACK', []),
        "logs": safe_logs,
        "announcements": DB.get('ANNOUNCEMENTS', [])
    })

@csrf_exempt
def api_profile(request):
    """Akademisyen Profil, Resim ve Telefon"""
    if request.method == "OPTIONS": return JsonResponse({})
    try:
        body = json.loads(request.body)
        name = body.get('name')
        norm_name = normalize_name(name)
        
        # 1. Akademisyen Bilgisi (academicians.json'dan)
        acc = None
        for email, p in DB['ACADEMICIANS'].items():
            if normalize_name(p.get("Fullname")) == norm_name:
                acc = p
                break
        if not acc: return JsonResponse({"error": "Bulunamadi"}, 404)

        # 2. Web Data'dan Ek Bilgiler (Resim ve Telefon)
        img_url = None
        phone_number = "-" # Varsayılan boş
        
        # Web Data içinde bu hocayı ara
        for w in DB['WEB_DATA']:
            if normalize_name(w.get("Fullname")) == norm_name:
                # A. Resim Yolu
                path_val = w.get("Image_Path")
                if path_val:
                    filename = path_val.replace('\\', '/').split('/')[-1]
                    img_url = f"{BASE_URL}/akademisyen_fotograflari/{filename}"
                
                # B. Telefon Numarası (Olası sütun isimleri)
                phone_number = w.get("Work_Phone") or w.get("Phone") or w.get("Telefon") or "-"
                break
        
        # Eğer web_data'da resim yoksa isimden tahmin et
        if not img_url:
            slug_name = slugify_name(name)
            img_url = f"{BASE_URL}/akademisyen_fotograflari/{slug_name}.jpg"

        # 3. Projeleri Bul (Aynı kalıyor)
        projects = []
        for m in DB['MATCHES']:
            if normalize_name(m.get('data')) == norm_name:
                pid = str(m.get('Column3') or m.get('project_id') or "")
                pd = DB['PROJECTS'].get(pid, {})
                
                decision = "waiting"
                for fb in DB['FEEDBACK']:
                    if normalize_name(fb.get("academician")) == norm_name and str(fb.get("projId")) == pid:
                        decision = fb.get("decision")
                        break
                
                collaborators = []
                for fb in DB['FEEDBACK']:
                    if str(fb.get("projId")) == pid and fb.get("decision") == "accepted":
                         if normalize_name(fb.get("academician")) != norm_name:
                            collaborators.append(fb.get("academician"))

                projects.append({
                    "id": pid,
                    "title": pd.get("title") or pd.get("acronym") or f"Proje-{pid}",
                    "score": int(m.get('Column7') or m.get('score') or 0),
                    "budget": pd.get("overall_budget", "-"),
                    "status": pd.get("status", "-"),
                    "objective": (pd.get("objective") or "")[:200] + "...",
                    "decision": decision,
                    "collaborators": collaborators,
                    "url": pd.get("url", "#")
                })
        
        projects.sort(key=lambda x: x['score'], reverse=True)
        
        return JsonResponse({
            "profile": {
                "Fullname": acc.get("Fullname"),
                "Email": acc.get("Email"),
                "Title": acc.get("Title"),
                "Field": acc.get("Field"),
                "Image": img_url,
                "Duties": acc.get("Duties", []),
                "Phone": phone_number  # <-- Telefon eklendi
            },
            "projects": projects
        })
    except Exception as e: return JsonResponse({"error": str(e)}, 500)


@csrf_exempt
def api_project_decision(request):
    """Karar Kaydetme (Kabul/Red)"""
    if request.method == "OPTIONS": return JsonResponse({})
    try:
        d = json.loads(request.body)
        # Varsa güncelle, yoksa ekle
        found = False
        for item in DB['FEEDBACK']:
            if item.get("academician") == d.get("academician") and str(item.get("projId")) == str(d.get("projId")):
                item.update(d)
                found = True
                break
        if not found: DB['FEEDBACK'].append(d)

        # Dosyaya yaz
        save_path = find_file('decisions.json') or os.path.join(BASE_DIR, 'decisions.json')
        with open(save_path, 'w') as f:
            json.dump(DB['FEEDBACK'], f)

        return JsonResponse({"status": "success"})
    except:
        return JsonResponse({}, 400)


@csrf_exempt
def api_top_projects(request):
    """En Çok Önerilen 50 Proje"""
    if request.method == "OPTIONS": return JsonResponse({})
    cnt = Counter()
    for m in DB['MATCHES']:
        pid = str(m.get('Column3') or m.get('project_id') or "").strip()
        if pid: cnt[pid] += 1

    top = []
    for pid, c in cnt.most_common(50):
        pd = DB['PROJECTS'].get(pid, {})
        title = pd.get("title") or pd.get("acronym") or pd.get("project_acronym") or f"Proje-{pid}"

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
    """Duyurular"""
    if request.method == "OPTIONS": return JsonResponse({})
    if request.method == "POST":
        d = json.loads(request.body)
        if d.get("action") == "delete":
            try:
                del DB['ANNOUNCEMENTS'][d["index"]]
            except:
                pass
        else:
            d["date"] = datetime.datetime.now().strftime("%d.%m.%Y")
            DB['ANNOUNCEMENTS'].insert(0, d)

        path = find_file('announcements.json') or os.path.join(BASE_DIR, 'announcements.json')
        with open(path, 'w') as f:
            json.dump(DB['ANNOUNCEMENTS'], f)
        return JsonResponse({"status": "success"})
    return JsonResponse(DB['ANNOUNCEMENTS'], safe=False)


@csrf_exempt
def api_messages(request):
    """Mesajlar: Yönetici hepsini görür"""
    if request.method == "OPTIONS": return JsonResponse({})
    
    if request.method == "POST":
        try:
            d = json.loads(request.body)
            action = d.get("action")

            if action == "list":
                current_user = d.get("user") or d.get("username")
                if not current_user: return JsonResponse([], safe=False)

                # Kullanıcı Adı Kontrolü (Büyük/Küçük harf duyarsız)
                u_str = str(current_user).lower().strip()
                
                # Yönetici mi?
                if u_str in ["admin", "yonetici", "yönetici", "administrator"]:
                    # Tüm mesajları gönder (Garanti liste)
                    msgs = DB.get('MESSAGES', [])
                    if not isinstance(msgs, list): msgs = []
                    return JsonResponse(msgs, safe=False)

                # Normal Kullanıcı ise Filtrele
                norm_user = normalize_name(current_user)
                filtered = []
                msgs = DB.get('MESSAGES', [])
                if not isinstance(msgs, list): msgs = []

                for m in msgs:
                    # Gönderen veya Alıcı alanlarını kontrol et
                    s = normalize_name(m.get("sender") or m.get("from"))
                    r = normalize_name(m.get("receiver") or m.get("to"))
                    if s == norm_user or r == norm_user:
                        filtered.append(m)
                
                return JsonResponse(filtered, safe=False)

            if action == "send":
                d['timestamp'] = datetime.datetime.now().strftime("%d.%m.%Y %H:%M:%S")
                
                if 'MESSAGES' not in DB or not isinstance(DB['MESSAGES'], list):
                    DB['MESSAGES'] = []
                DB['MESSAGES'].append(d)
                
                # Kaydet
                path = find_file('messages.json')
                if not path: path = os.path.join(BASE_DIR, 'messages.json')
                try:
                    with open(path, 'w', encoding='utf-8') as f:
                        json.dump(DB['MESSAGES'], f, indent=4)
                except: pass
                    
                return JsonResponse({"status": "success"})

        except Exception as e:
            return JsonResponse({"error": str(e)}, 400)
            
    return JsonResponse([], safe=False)
    

@csrf_exempt
def api_network_graph(request):
    """İşbirliği Ağı Verisi"""
    if request.method == "OPTIONS": return JsonResponse({})
    user = request.GET.get('user')
    if not user: return JsonResponse({"nodes": [], "links": []})

    norm_user = normalize_name(user)
    nodes = [{"id": user, "group": 1, "isCenter": True, "img": get_image_url_for_name(user)}]
    links = []
    added_nodes = {norm_user}

    # Kullanıcının kabul ettiği projeler
    my_projects = set()
    for fb in DB['FEEDBACK']:
        if normalize_name(fb.get("academician")) == norm_user and fb.get("decision") == "accepted":
            my_projects.add(str(fb.get("projId")))

    # Ortakları bul
    collaborators = set()
    for fb in DB['FEEDBACK']:
        p_id = str(fb.get("projId"))
        p_acc = fb.get("academician")
        # Eğer ortak proje varsa ve kişi ben değilsem
        if p_id in my_projects and normalize_name(p_acc) != norm_user and fb.get("decision") == "accepted":
            collaborators.add(p_acc)

    for col in collaborators:
        if normalize_name(col) in added_nodes: continue
        nodes.append({"id": col, "group": 2, "img": get_image_url_for_name(col)})
        links.append({"source": user, "target": col})
        added_nodes.add(normalize_name(col))

    return JsonResponse({"nodes": nodes, "links": links})


# ==========================================
# 7. DOSYA SUNUCUSU (FILE SERVER) - ROBUST
# ==========================================
def serve_file(request, folder, filename):
    """
    Linux/Windows fark etmeksizin dosyayı bulur ve sunar.
    Büyük/Küçük harf duyarlılığını ortadan kaldırır.
    """
    # 1. Klasörü Bul
    target_folder = folder.lower()
    folder_path = None

    # Önce doğrudan dene
    if os.path.exists(os.path.join(BASE_DIR, folder)):
        folder_path = os.path.join(BASE_DIR, folder)
    else:
        # Bulamazsan tara
        for f in os.listdir(BASE_DIR):
            if os.path.isdir(os.path.join(BASE_DIR, f)):
                if f.lower() == target_folder:
                    folder_path = os.path.join(BASE_DIR, f)
                    break

    if not folder_path:
        return HttpResponse(f"Klasor Yok: {folder}", status=404)

    # 2. Dosyayı Bul
    target_file = filename.lower()
    for f in os.listdir(folder_path):
        if f.lower() == target_file:
            full_path = os.path.join(folder_path, f)
            # İçeriği sun
            content_type, _ = mimetypes.guess_type(full_path)
            return FileResponse(open(full_path, 'rb'), content_type=content_type or 'image/jpeg')

    return HttpResponse(f"Dosya Yok: {filename}", status=404)


# ==========================================
# 8. URL YÖNLENDİRMELERİ
# ==========================================
urlpatterns = [
    path('', index),
    path('api/test/', api_test_data),
    path('api/login/', api_login),
    path('api/change-password/', api_change_password), # <-- Frontend isteğine uygun isim
    path('api/logout/', api_logout),
    path('api/admin-data/', api_admin_data),
    path('api/profile/', api_profile),
    path('api/decision/', api_project_decision),
    path('api/top-projects/', api_top_projects),
    path('api/announcements/', api_announcements),
    path('api/messages/', api_messages),
    path('api/network-graph/', api_network_graph),
    # Resim yolları
    path('images/<str:filename>', lambda r, filename: serve_file(r, 'images', filename)),
    path('akademisyen_fotograflari/<str:filename>',
         lambda r, filename: serve_file(r, 'akademisyen_fotograflari', filename)),
]

application = get_wsgi_application()

if __name__ == "__main__":
    execute_from_command_line(sys.argv)
