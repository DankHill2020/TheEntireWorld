// Tech Connector Mobile Remote App with Universal i18n & Graph Engine
"use strict";

const universalLanguages = [
  { code: "en", name: "English", flag: "🇬🇧" },
  { code: "es", name: "Español", flag: "🇪🇸" },
  { code: "fr", name: "Français", flag: "🇫🇷" },
  { code: "de", name: "Deutsch", flag: "🇩🇪" },
  { code: "zh", name: "中文 (简体)", flag: "🇨🇳" },
  { code: "zh-TW", name: "中文 (繁體)", flag: "🇹🇼" },
  { code: "ja", name: "日本語", flag: "🇯🇵" },
  { code: "ko", name: "한국어", flag: "🇰🇷" },
  { code: "pt", name: "Português", flag: "🇵🇹" },
  { code: "it", name: "Italiano", flag: "🇮🇹" },
  { code: "ru", name: "Русский", flag: "🇷🇺" },
  { code: "ar", name: "العربية", flag: "🇸🇦", rtl: true },
  { code: "hi", name: "हिन्दी", flag: "🇮🇳" },
  { code: "bn", name: "বাংলা", flag: "🇧🇩" },
  { code: "pa", name: "ਪੰਜਾਬੀ", flag: "🇮🇳" },
  { code: "jv", name: "Basa Jawa", flag: "🇮🇩" },
  { code: "vi", name: "Tiếng Việt", flag: "🇻🇳" },
  { code: "te", name: "తెలుగు", flag: "🇮🇳" },
  { code: "mr", name: "मराठी", flag: "🇮🇳" },
  { code: "ta", name: "தமிழ்", flag: "🇮🇳" },
  { code: "ur", name: "اردو", flag: "🇵🇰", rtl: true },
  { code: "tr", name: "Türkçe", flag: "🇹🇷" },
  { code: "th", name: "ไทย", flag: "🇹🇭" },
  { code: "gu", name: "ગુજરાતી", flag: "🇮🇳" },
  { code: "fa", name: "فارسی", flag: "🇮🇷", rtl: true },
  { code: "pl", name: "Polski", flag: "🇵🇱" },
  { code: "ps", name: "پښتو", flag: "🇦🇫", rtl: true },
  { code: "kn", name: "ಕನ್ನಡ", flag: "🇮🇳" },
  { code: "ml", name: "മലയാളം", flag: "🇮🇳" },
  { code: "su", name: "Basa Sunda", flag: "🇮🇩" },
  { code: "ha", name: "Hausa", flag: "🇳🇬" },
  { code: "or", name: "ଓଡ଼ିଆ", flag: "🇮🇳" },
  { code: "my", name: "မြန်မာစာ", flag: "🇲🇲" },
  { code: "uk", name: "Українська", flag: "🇺🇦" },
  { code: "fil", name: "Filipino / Tagalog", flag: "🇵🇭" },
  { code: "sw", name: "Kiswahili", flag: "🇰🇪" },
  { code: "uz", name: "Oʻzbekcha", flag: "🇺🇿" },
  { code: "ro", name: "Română", flag: "🇷🇴" },
  { code: "nl", name: "Nederlands", flag: "🇳🇱" },
  { code: "el", name: "Ελληνικά", flag: "🇬🇷" },
  { code: "hu", name: "Magyar", flag: "🇭🇺" },
  { code: "cs", name: "Čeština", flag: "🇨🇿" },
  { code: "sv", name: "Svenska", flag: "🇸🇪" },
  { code: "he", name: "עברית", flag: "🇮🇱", rtl: true },
  { code: "fi", name: "Suomi", flag: "🇫🇮" },
  { code: "no", name: "Norsk", flag: "🇳🇴" },
  { code: "da", name: "Dansk", flag: "🇩🇰" },
  { code: "id", name: "Bahasa Indonesia", flag: "🇮🇩" },
  { code: "ms", name: "Bahasa Melayu", flag: "🇲🇾" },
  { code: "am", name: "አማርኛ", flag: "🇪🇹" },
];

const rtlLanguages = new Set(["ar", "he", "fa", "ur", "ps", "sd", "yi", "ug", "ckb", "dv"]);

const i18n = {
  en: {
    workstation_pair: "Workstation Pair", tab_2fa: "🛡️ 2FA Security", two_factor_title: "Two-Factor Authentication", two_factor_help: "Enter the 6-digit security code displayed on your workstation.", verify_2fa_btn: "Verify 2FA Code", resend_2fa_btn: "Request New Code on PC",
    pair_description: "Pair your mobile device with your desktop workstation to control pipelines, build graphs, and stream live app viewports.",
    tab_qr: "📸 QR Scanner",
    tab_autodetect: "🔍 Auto-Detect LAN",
    tab_manual: "🔑 Token / Link",
    scan_qr_btn: "Scan Workstation QR Code",
    point_camera_help: "Point your camera at the QR code shown in Tech Connector on your workstation.",
    lan_scan_help: "Scan your local network for running Tech Connector workstations.",
    auto_detect_btn: "⚡ Auto-Detect Workstation",
    manual_link_help: "Paste the full connection link or token from Tech Connector menu.",
    connect_btn: "Connect",
    header_subtitle: "Mobile Control Surface & Live Stream",
    connecting: "Connecting",
    repair_btn: "⚡ Re-Pair",
    install_btn: "Install App",
    refresh_btn: "Refresh",
  },
  es: {
    workstation_pair: "Emparejar Estación de Trabajo",
    pair_description: "Empareja tu dispositivo móvil con tu PC para controlar pipelines, crear grafos y transmitir vistas en vivo.",
    tab_qr: "📸 Escáner QR",
    tab_autodetect: "🔍 Auto-Detectar LAN",
    tab_manual: "🔑 Token / Enlace",
    scan_qr_btn: "Escanear Código QR",
    point_camera_help: "Apunta la cámara al código QR que aparece en Tech Connector en tu PC.",
    lan_scan_help: "Busca estaciones de trabajo Tech Connector en tu red local.",
    auto_detect_btn: "⚡ Detectar Estación",
    manual_link_help: "Pega el enlace completo de conexión o el token.",
    connect_btn: "Conectar",
    header_subtitle: "Superficie de Control Móvil y Transmisión",
    connecting: "Conectando",
    repair_btn: "⚡ Re-Emparejar",
    install_btn: "Instalar App",
    refresh_btn: "Actualizar",
  },
  fr: {
    workstation_pair: "Appairer la Station",
    pair_description: "Appairez votre appareil mobile avec votre PC pour contrôler les pipelines et diffuser les vues en direct.",
    tab_qr: "📸 Scanner QR",
    tab_autodetect: "🔍 Auto-Détection LAN",
    tab_manual: "🔑 Jeton / Lien",
    scan_qr_btn: "Scanner le Code QR",
    point_camera_help: "Pointez votre caméra vers le code QR affiché sur votre PC.",
    lan_scan_help: "Recherchez les stations Tech Connector sur votre réseau local.",
    auto_detect_btn: "⚡ Détecter la Station",
    manual_link_help: "Collez le lien complet de connexion ou le jeton.",
    connect_btn: "Connecter",
    header_subtitle: "Surface de Contrôle Mobile et Flux en Direct",
    connecting: "Connexion",
    repair_btn: "⚡ Réappairer",
    install_btn: "Installer l'App",
    refresh_btn: "Actualiser",
  },
  de: {
    workstation_pair: "Workstation Koppeln",
    pair_description: "Koppeln Sie Ihr Mobilgerät mit Ihrer Workstation zur Steuerung von Pipelines und Live-Streams.",
    tab_qr: "📸 QR Scanner",
    tab_autodetect: "🔍 LAN Auto-Erkennung",
    tab_manual: "🔑 Token / Link",
    scan_qr_btn: "QR-Code Scannen",
    point_camera_help: "Richten Sie Ihre Kamera auf den QR-Code in Tech Connector.",
    lan_scan_help: "Suchen Sie im lokalen Netzwerk nach laufenden Workstations.",
    auto_detect_btn: "⚡ Workstation Erkennen",
    manual_link_help: "Fügen Sie den vollständigen Verbindungslink oder Token ein.",
    connect_btn: "Verbinden",
    header_subtitle: "Mobile Steuerung & Live-Stream",
    connecting: "Verbinden...",
    repair_btn: "⚡ Neu Koppeln",
    install_btn: "App Installieren",
    refresh_btn: "Aktualisieren",
  },
  zh: {
    workstation_pair: "配对工作站",
    pair_description: "将移动设备与桌面工作站配对，控制管线、构建图表并实时流式传输视图。",
    tab_qr: "📸 扫码配对",
    tab_autodetect: "🔍 局域网自动检测",
    tab_manual: "🔑 令牌 / 链接",
    scan_qr_btn: "扫描工作站二维码",
    point_camera_help: "将摄像头对准电脑上 Tech Connector 显示的二维码。",
    lan_scan_help: "扫描本地网络中正在运行的工作站。",
    auto_detect_btn: "⚡ 自动检测工作站",
    manual_link_help: "粘贴完整的连接链接或令牌。",
    connect_btn: "连接",
    header_subtitle: "移动控制面板与实时流",
    connecting: "连接中",
    repair_btn: "⚡ 重新配对",
    install_btn: "安装应用",
    refresh_btn: "刷新",
  },
  ja: {
    workstation_pair: "ワークステーションペアリング",
    pair_description: "モバイル端末をPCとペアリングして、パイプラインの制御やライブ配信を行います。",
    tab_qr: "📸 QRスキャナー",
    tab_autodetect: "🔍 LAN自動検出",
    tab_manual: "🔑 トークン / リンク",
    scan_qr_btn: "QRコードをスキャン",
    point_camera_help: "カメラをPCのTech Connectorに表示されたQRコードに向けてください。",
    lan_scan_help: "ローカルネットワーク内のワークステーションを検索します。",
    auto_detect_btn: "⚡ ワークステーション自動検出",
    manual_link_help: "接続リンクまたはトークンを貼り付けてください。",
    connect_btn: "接続",
    header_subtitle: "モバイルコントロール＆ライブストリーム",
    connecting: "接続中",
    repair_btn: "⚡ 再ペアリング",
    install_btn: "アプリをインストール",
    refresh_btn: "更新",
  },
  ko: {
    workstation_pair: "워크스테이션 페어링",
    pair_description: "모바일 기기를 PC와 연결하여 파이프라인 제어 및 라이브 뷰 스트리밍을 실행합니다.",
    tab_qr: "📸 QR 스캐너",
    tab_autodetect: "🔍 LAN 자동 감지",
    tab_manual: "🔑 토큰 / 링크",
    scan_qr_btn: "QR 코드 스캔",
    point_camera_help: "PC 화면의 Tech Connector QR 코드를 카메라로 비춰주세요.",
    lan_scan_help: "로컬 네트워크에서 실행 중인 워크스테이션을 검색합니다.",
    auto_detect_btn: "⚡ 워크스테이션 자동 감지",
    manual_link_help: "전체 연결 링크 또는 토큰을 붙여넣으세요.",
    connect_btn: "연결",
    header_subtitle: "모바일 제어 및 라이브 스트림",
    connecting: "연결 중",
    repair_btn: "⚡ 재페어링",
    install_btn: "앱 설치",
    refresh_btn: "새로고침",
  },
  pt: {
    workstation_pair: "Emparelhar Estação",
    pair_description: "Emparelhe seu dispositivo móvel com sua estação de trabalho para controlar pipelines e transmissão ao vivo.",
    tab_qr: "📸 Leitor QR",
    tab_autodetect: "🔍 Detecção LAN",
    tab_manual: "🔑 Token / Link",
    scan_qr_btn: "Escanear QR Code",
    point_camera_help: "Aponte a câmera para o QR Code exibido no Tech Connector.",
    lan_scan_help: "Procure estações de trabalho ativas na sua rede local.",
    auto_detect_btn: "⚡ Detectar Estação",
    manual_link_help: "Cole o link de conexão completo ou o token.",
    connect_btn: "Conectar",
    header_subtitle: "Superfície de Controle Móvel e Transmissão",
    connecting: "Conectando",
    repair_btn: "⚡ Reemparelhar",
    install_btn: "Instalar App",
    refresh_btn: "Atualizar",
  },
  it: {
    workstation_pair: "Associa Workstation",
    pair_description: "Associa il tuo dispositivo mobile alla tua workstation per controllare le pipeline e lo streaming live.",
    tab_qr: "📸 Scanner QR",
    tab_autodetect: "🔍 Rileva in LAN",
    tab_manual: "🔑 Token / Link",
    scan_qr_btn: "Scansiona Codice QR",
    point_camera_help: "Inquadra il codice QR mostrato in Tech Connector sul PC.",
    lan_scan_help: "Cerca workstation attive nella tua rete locale.",
    auto_detect_btn: "⚡ Rileva Workstation",
    manual_link_help: "Incolla il link di connessione completo o il token.",
    connect_btn: "Connetti",
    header_subtitle: "Superficie di Controllo Mobile e Streaming",
    connecting: "Connessione...",
    repair_btn: "⚡ Riassocia",
    install_btn: "Installa App",
    refresh_btn: "Aggiorna",
  },
  ru: {
    workstation_pair: "Спряжение с ПК",
    pair_description: "Свяжите мобильное устройство с рабочей станцией для управления пайплайнами и трансляции в реальном времени.",
    tab_qr: "📸 QR Сканер",
    tab_autodetect: "🔍 Автопоиск в LAN",
    tab_manual: "🔑 Токен / Ссылка",
    scan_qr_btn: "Сканировать QR-код",
    point_camera_help: "Наведите камеру на QR-код в Tech Connector на ПК.",
    lan_scan_help: "Поиск рабочих станций в вашей локальной сети.",
    auto_detect_btn: "⚡ Найти ПК",
    manual_link_help: "Вставьте полную ссылку подключения или токен.",
    connect_btn: "Подключиться",
    header_subtitle: "Панель управления и трансляция",
    connecting: "Подключение...",
    repair_btn: "⚡ Повторить связь",
    install_btn: "Установить",
    refresh_btn: "Обновить",
  },
  ar: {
    workstation_pair: "اقتران محطة العمل",
    pair_description: "اقرن جهازك المحمول بمحطة العمل للتحكم في الأنابيب وبناء المخططات والبث المباشر.",
    tab_qr: "📸 ماسح QR",
    tab_autodetect: "🔍 الكشف التلقائي LAN",
    tab_manual: "🔑 رمز / رابط",
    scan_qr_btn: "مسح رمز QR",
    point_camera_help: "وجّه الكاميرا إلى رمز QR المعروض في Tech Connector على جهازك.",
    lan_scan_help: "ابحث في الشبكة المحلية عن محطات العمل النشطة.",
    auto_detect_btn: "⚡ كشف محطة العمل",
    manual_link_help: "الصق رابط الاتصال الكامل أو الرمز المميز.",
    connect_btn: "اتصال",
    header_subtitle: "لوحة التحكم المحمولة والبث المباشر",
    connecting: "جاري الاتصال",
    repair_btn: "⚡ إعادة الاقتران",
    install_btn: "تثبيت التطبيق",
    refresh_btn: "تحديث",
  },
  hi: {
    workstation_pair: "वर्कस्टेशन पेयरिंग",
    pair_description: "पाइपलाइन नियंत्रित करने और लाइव स्ट्रीम के लिए अपने मोबाइल को वर्कस्टेशन से जोड़ें।",
    tab_qr: "📸 QR स्कैनर",
    tab_autodetect: "🔍 ऑटो-डिटेक्ट LAN",
    tab_manual: "🔑 टोकन / लिंक",
    scan_qr_btn: "QR कोड स्कैन करें",
    point_camera_help: "अपने पीसी पर Tech Connector में दिखाई दे रहे QR कोड पर कैमरा ले जाएं।",
    lan_scan_help: "अपने स्थानीय नेटवर्क पर सक्रिय वर्कस्टेशन खोजें।",
    auto_detect_btn: "⚡ वर्कस्टेशन डिटेक्ट करें",
    manual_link_help: "पूरा कनेक्शन लिंक या टोकन पेस्ट करें।",
    connect_btn: "कनेक्ट करें",
    header_subtitle: "मोबाइल कंट्रोल और लाइव स्ट्रीम",
    connecting: "कनेक्ट हो रहा है",
    repair_btn: "⚡ पुनः पेयर करें",
    install_btn: "ऐप इंस्टॉल करें",
    refresh_btn: "रिफ्रेश",
  },
  nl: {
    workstation_pair: "Koppel Workstation",
    pair_description: "Koppel je mobiele apparaat met je workstation om pipelines te beheren en live te streamen.",
    tab_qr: "📸 QR Scanner",
    tab_autodetect: "🔍 Auto-Detect LAN",
    tab_manual: "🔑 Token / Link",
    scan_qr_btn: "Scan QR Code",
    point_camera_help: "Richt je camera op de QR-code in Tech Connector op je PC.",
    lan_scan_help: "Zoek in je lokale netwerk naar actieve workstations.",
    auto_detect_btn: "⚡ Detecteer Workstation",
    manual_link_help: "Plak de volledige verbindingslink of token.",
    connect_btn: "Verbinden",
    header_subtitle: "Mobiel Bedieningspaneel & Live Stream",
    connecting: "Verbinden...",
    repair_btn: "⚡ Herkoppelen",
    install_btn: "App Installeren",
    refresh_btn: "Vernieuwen",
  },
  tr: {
    workstation_pair: "İstasyon Eşleştirme",
    pair_description: "Mobil cihazınızı iş istasyonunuzla eşleştirerek boru hatlarını yönetin ve canlı yayın yapın.",
    tab_qr: "📸 QR Tarayıcı",
    tab_autodetect: "🔍 Otomatik Oturum LAN",
    tab_manual: "🔑 Jeton / Bağlantı",
    scan_qr_btn: "QR Kodunu Tara",
    point_camera_help: "Kameranızı PC'deki Tech Connector QR koduna doğrultun.",
    lan_scan_help: "Yerel ağınızdaki çalışan iş istasyonlarını arayın.",
    auto_detect_btn: "⚡ İstasyonu Algıla",
    manual_link_help: "Tam bağlantı adresini veya jetonu yapıştırın.",
    connect_btn: "Bağlan",
    header_subtitle: "Mobil Kontrol Yüzeyi ve Canlı Yayın",
    connecting: "Bağlanıyor...",
    repair_btn: "⚡ Yeniden Eşle",
    install_btn: "Uygulamayı Yükle",
    refresh_btn: "Yenile",
  },
  pl: {
    workstation_pair: "Parowanie Stacji",
    pair_description: "Sparuj urządzenie mobilne ze stacją roboczą, aby sterować potokami i transmitować na żywo.",
    tab_qr: "📸 Skaner QR",
    tab_autodetect: "🔍 Wykryj w LAN",
    tab_manual: "🔑 Token / Link",
    scan_qr_btn: "Skanuj Kod QR",
    point_camera_help: "Skieruj aparat na kod QR w Tech Connector na komputerze.",
    lan_scan_help: "Szukaj aktywnych stacji w sieci lokalnej.",
    auto_detect_btn: "⚡ Wykryj Stację",
    manual_link_help: "Wklej pełny link połączenia lub token.",
    connect_btn: "Połącz",
    header_subtitle: "Mobilny Panel Sterowania i Stream",
    connecting: "Łączenie...",
    repair_btn: "⚡ Sparuj Ponownie",
    install_btn: "Zainstaluj Aplikację",
    refresh_btn: "Odśwież",
  },
};

const statusTranslations = {
  en: { running: "Running", completed: "Completed", failed: "Failed", pending: "Pending", cancelled: "Cancelled", active: "Active", finished: "Finished", online: "Online", offline: "Offline", no_jobs: "No active jobs", no_finished: "No finished jobs", no_events: "No live events" },
  es: { running: "Ejecutando", completed: "Completado", failed: "Fallido", pending: "Pendiente", cancelled: "Cancelado", active: "Activo", finished: "Finalizado", online: "En línea", offline: "Desconectado", no_jobs: "Sin tareas activas", no_finished: "Sin tareas finalizadas", no_events: "Sin eventos" },
  fr: { running: "En cours", completed: "Terminé", failed: "Échec", pending: "En attente", cancelled: "Annulé", active: "Actif", finished: "Terminé", online: "En ligne", offline: "Hors ligne", no_jobs: "Aucune tâche active", no_finished: "Aucune tâche terminée", no_events: "Aucun événement" },
  de: { running: "Läuft", completed: "Abgeschlossen", failed: "Fehlgeschlagen", pending: "Ausstehend", cancelled: "Abgebrochen", active: "Aktiv", finished: "Beendet", online: "Online", offline: "Offline", no_jobs: "Keine aktiven Aufgaben", no_finished: "Keine beendeten Aufgaben", no_events: "Keine Ereignisse" },
  zh: { running: "运行中", completed: "已完成", failed: "失败", pending: "等待中", cancelled: "已取消", active: "活动", finished: "已结束", online: "在线", offline: "离线", no_jobs: "无活动任务", no_finished: "无已完成任务", no_events: "无实时事件" },
  ja: { running: "実行中", completed: "完了", failed: "失敗", pending: "保留中", cancelled: "キャンセル済み", active: "アクティブ", finished: "終了", online: "オンライン", offline: "オフライン", no_jobs: "アクティブなジョブなし", no_finished: "終了したジョブなし", no_events: "イベントなし" },
  ko: { running: "실행 중", completed: "완료됨", failed: "실패함", pending: "대기 중", cancelled: "취소됨", active: "활성", finished: "종료됨", online: "온라인", offline: "오프라인", no_jobs: "활성 작업 없음", no_finished: "종료된 작업 없음", no_events: "이벤트 없음" },
  pt: { running: "Em execução", completed: "Concluído", failed: "Falhou", pending: "Pendente", cancelled: "Cancelado", active: "Ativo", finished: "Finalizado", online: "Online", offline: "Offline", no_jobs: "Sem tarefas ativas", no_finished: "Sem tarefas finalizadas", no_events: "Sem eventos" },
  it: { running: "In esecuzione", completed: "Completato", failed: "Fallito", pending: "In attesa", cancelled: "Annullato", active: "Attivo", finished: "Terminato", online: "Online", offline: "Offline", no_jobs: "Nessun lavoro attivo", no_finished: "Nessun lavoro terminato", no_events: "Nessun evento" },
  ru: { running: "Выполняется", completed: "Завершено", failed: "Ошибка", pending: "В очереди", cancelled: "Отменено", active: "Активно", finished: "Завершено", online: "В сети", offline: "Офлайн", no_jobs: "Нет активных задач", no_finished: "Нет завершенных задач", no_events: "Нет событий" },
  ar: { running: "قيد التشغيل", completed: "مكتمل", failed: "فشل", pending: "معلق", cancelled: "ملغى", active: "نشط", finished: "منتهي", online: "متصل", offline: "غير متصل", no_jobs: "لا توجد مهام نشطة", no_finished: "لا توجد مهام منتهية", no_events: "لا توجد أحداث" },
  hi: { running: "चल रहा है", completed: "पूरा हुआ", failed: "विफल", pending: "लंबित", cancelled: "रद्द किया गया", active: "सक्रिय", finished: "समाप्त", online: "ऑनलाइन", offline: "ऑफ़लाइन", no_jobs: "कोई सक्रिय कार्य नहीं", no_finished: "कोई समाप्त कार्य नहीं", no_events: "कोई लाइव ईवेंट नहीं" },
  nl: { running: "Bezig", completed: "Voltooid", failed: "Mislukt", pending: "In afwachting", cancelled: "Geannuleerd", active: "Actief", finished: "Voltooid", online: "Online", offline: "Offline", no_jobs: "Geen actieve taken", no_finished: "Geen voltooide taken", no_events: "Geen gebeurtenissen" },
  tr: { running: "Çalışıyor", completed: "Tamamlandı", failed: "Başarısız", pending: "Beklemede", cancelled: "İptal edildi", active: "Etkin", finished: "Bitti", online: "Çevrimiçi", offline: "Çevrimdışı", no_jobs: "Etkin iş yok", no_finished: "Biten iş yok", no_events: "Canlı olay yok" },
  pl: { running: "W trakcie", completed: "Zakończono", failed: "Niepowodzenie", pending: "Oczekuje", cancelled: "Anulowano", active: "Aktywny", finished: "Zakończony", online: "Online", offline: "Offline", no_jobs: "Brak aktywnych zadań", no_finished: "Brak zakończonych zadań", no_events: "Brak zdarzeń" },
};

function getSystemLanguage() {
  const stored = localStorage.aiStudioRemoteLang;
  if (stored && (i18n[stored] || universalLanguages.some((l) => l.code === stored))) return stored;
  const navLang = (navigator.language || "").split("-")[0].toLowerCase();
  return i18n[navLang] ? navLang : "en";
}

let currentLang = getSystemLanguage();

function populateLanguageSelects() {
  const optionsHtml = universalLanguages.map((l) => `<option value="${l.code}">${l.flag} ${l.name}</option>`).join("");
  document.querySelectorAll(".lang-select").forEach((select) => {
    const val = select.value || currentLang;
    select.innerHTML = optionsHtml;
    select.value = val;
  });
}

function translateStatus(key) {
  const langDict = statusTranslations[currentLang] || statusTranslations.en;
  return langDict[key.toLowerCase()] || key;
}

function applyTranslations(lang) {
  currentLang = lang || currentLang;
  localStorage.aiStudioRemoteLang = currentLang;

  document.documentElement.dir = rtlLanguages.has(currentLang) ? "rtl" : "ltr";
  document.documentElement.lang = currentLang;

  populateLanguageSelects();

  const dict = i18n[currentLang] || i18n.en;
  document.querySelectorAll("[data-i18n]").forEach((el) => {
    const key = el.dataset.i18n;
    if (dict[key]) {
      el.textContent = dict[key];
    }
  });
}

const params = new URLSearchParams(location.search);
const state = {
  token: params.get("token") || localStorage.aiStudioRemoteToken || "",
  serverBase: params.get("server") || localStorage.aiStudioRemoteServerBase || "",
  status: {},
  applications: [],
  applicationProgress: {},
  pipelines: [],
  activeJobs: [],
  finishedJobs: [],
  events: [],
  jobSteps: [],
  installPrompt: null,
  pressTimer: null,
  scale: 1,
};

const graphState = {
  pipeline_id: "",
  name: "Mobile Graph Workflow",
  host: "general",
  goal: "",
  nodes: [
    {
      id: "node_1",
      label: "inspect_scene",
      package: "Maya",
      type: "Inspect",
      detail: "Read active Maya scene, camera, and hierarchy",
      params: [{ name: "file_path", annotation: "file_path" }],
      outputs: [{ name: "scene_info", annotation: "dict" }],
      literal_values: { file_path: "" },
      x: 40,
      y: 60,
      status: "idle",
    },
    {
      id: "node_2",
      label: "create_rig_mapping",
      package: "Maya",
      type: "DCC Command",
      detail: "Map skeleton joints to HumanIK definition",
      params: [{ name: "character_name", annotation: "str" }, { name: "joint_mapping", annotation: "dict" }],
      outputs: [{ name: "hik_character", annotation: "str" }],
      literal_values: { character_name: "HeroRig" },
      x: 320,
      y: 60,
      status: "idle",
    },
    {
      id: "node_3",
      label: "generate_report",
      package: "Utility",
      type: "Report",
      detail: "Compile pipeline execution report log",
      params: [{ name: "summary_text", annotation: "str" }],
      outputs: [{ name: "report_data", annotation: "dict" }],
      literal_values: { summary_text: "Auto-generated report from mobile" },
      x: 600,
      y: 60,
      status: "idle",
    },
  ],
  data_links: [
    { from_node: "node_1", from_port: "scene_info", to_node: "node_2", to_port: "character_name" },
  ],
  flow_links: [
    { from_node: "node_1", to_node: "node_2" },
    { from_node: "node_2", to_node: "node_3" },
  ],
  selectedNodeId: "node_1",
  activeAppTarget: "desktop",
  splitViewActive: false,
  draggingNodeId: null,
  dragOffsetX: 0,
  dragOffsetY: 0,
  connectingPin: null,
  catalog: [],
};

const els = {
  pairScreen: document.getElementById("pairScreen"),
  stage: document.getElementById("stage"),
  viewport: document.getElementById("viewport"),
  connectPanel: document.getElementById("connectPanel"),
  tokenInput: document.getElementById("tokenInput"),
  pairUrlInput: document.getElementById("pairUrlInput"),
  pairScanner: document.getElementById("pairScanner"),
  qrVideo: document.getElementById("qrVideo"),
  online: document.getElementById("online"),
  project: document.getElementById("project"),
  model: document.getElementById("model"),
  status: document.getElementById("status"),
  prompt: document.getElementById("prompt"),
  jobTitle: document.getElementById("jobTitle"),
  jobProvider: document.getElementById("jobProvider"),
  jobSteps: document.getElementById("jobSteps"),
  applicationsList: document.getElementById("applicationsList"),
  activeJobsList: document.getElementById("activeJobsList"),
  finishedJobsList: document.getElementById("finishedJobsList"),
  jobDetail: document.getElementById("jobDetail"),
  pipelinesList: document.getElementById("pipelinesList"),
  pipelineFilter: document.getElementById("pipelineFilter"),
  screenImage: document.getElementById("screenImage"),
  screenStatus: document.getElementById("screenStatus"),
  appTargetSelect: document.getElementById("appTargetSelect"),
  eventsList: document.getElementById("eventsList"),
  menu: document.getElementById("menu"),
  installHelp: document.getElementById("installHelp"),
  workspaceLayout: document.getElementById("workspaceLayout"),
  nodeGraphCanvas: document.getElementById("nodeGraphCanvas"),
  graphCanvasContainer: document.getElementById("graphCanvasContainer"),
  svgWireLayer: document.getElementById("svgWireLayer"),
  nodeContainer: document.getElementById("nodeContainer"),
  attributeInspector: document.getElementById("attributeInspector"),
  inspectorNodeKind: document.getElementById("inspectorNodeKind"),
  inspectorBody: document.getElementById("inspectorBody"),
  screenShareDrawer: document.getElementById("screenShareDrawer"),
  screenFrame: document.getElementById("screenFrame"),
  hudTelemetry: document.getElementById("hudTelemetry"),
  virtualCursor: document.getElementById("virtualCursor"),
  streamFpsSelect: document.getElementById("streamFpsSelect"),
  controlModeStatus: document.getElementById("controlModeStatus"),
  trackpadToggleBtn: document.getElementById("trackpadToggleBtn"),
  screenTargetBadgeText: document.getElementById("screenTargetBadgeText"),
  nodePaletteModal: document.getElementById("nodePaletteModal"),
  paletteFilter: document.getElementById("paletteFilter"),
  palettePackageFilter: document.getElementById("palettePackageFilter"),
  paletteCatalogList: document.getElementById("paletteCatalogList"),
};


function initSplashVideo() {
  const splashEl = document.getElementById("splashScreen");
  const splashVid = document.getElementById("splashVideo");
  if (!splashEl) return;

  const dismissSplash = () => {
    splashEl.classList.add("fade-out");
    setTimeout(() => { if (splashEl.parentNode) splashEl.remove(); }, 700);
  };

  if (splashVid) {
    splashVid.play().catch(() => {});
    splashVid.addEventListener("ended", dismissSplash);
  }
  setTimeout(dismissSplash, 2600);
}

function currentOrigin() {
  if (state.serverBase) return state.serverBase.replace(/\/+$/, "");
  if (location.protocol === "http:" || location.protocol === "https:") return location.origin;
  return "";
}

function apiUrl(path) {
  const base = currentOrigin();
  return base ? `${base}${path}` : path;
}

function escapeHtml(text) {
  return String(text ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function applyZoom() {
  els.stage.style.transform = `scale(${state.scale})`;
  els.stage.style.transformOrigin = "top left";
  els.viewport.style.overflow = state.scale > 1 ? "auto" : "hidden";
}

function zoomBy(factor) {
  state.scale = Math.min(Math.max(state.scale * factor, 0.6), 2.5);
  initSplashVideo();
applyZoom();
}

function zoomReset() {
  state.scale = 1;
  initSplashVideo();
applyZoom();
}

function setPaired(isPaired) {
  document.body.classList.toggle("paired", isPaired);
  els.pairScreen.hidden = isPaired;
}


function getOtpCode() {
  return Array.from(document.querySelectorAll(".otp-digit")).map((i) => i.value).join("");
}




let pendingSharePayload = { content: "", title: "", targetChannel: null };

const defaultSmartChannels = [
  { platform: "slack", target: "general", name: "#general (Slack)", icon: "💬" },
  { platform: "slack", target: "pipeline_builds", name: "#pipeline_builds (Slack)", icon: "💬" },
  { platform: "discord", target: "renders", name: "#renders (Discord)", icon: "🎮" },
  { platform: "discord", target: "maya_output", name: "#maya_output (Discord)", icon: "🎮" },
  { platform: "jira", target: "PROJ", name: "PROJ (Jira Task)", icon: "📋" },
  { platform: "jira", target: "MAYA", name: "MAYA (Jira Task)", icon: "📋" },
  { platform: "confluence", target: "DOCS", name: "DOCS (Confluence Page)", icon: "📚" },
  { platform: "docs", target: "wiki", name: "Wiki Documentation", icon: "📖" },
  { platform: "clickup", target: "TASKS", name: "TASKS (ClickUp Task)", icon: "🎯" },
];


let fetchedSmartChannels = [];

async function loadLiveSmartChannels() {
  try {
    const data = await command("list_smart_channels", {});
    if (data.ok) {
      fetchedSmartChannels = [...(data.channels || []), ...(data.users || [])];
      state.slackConnected = data.slack_connected;
      state.discordConnected = data.discord_connected;
    }
  } catch (_e) {}
  if (!fetchedSmartChannels.length) {
    fetchedSmartChannels = defaultSmartChannels;
  }
}

async function openSmartChannelPicker(content, title = "Code Snippet / Message") {
  await loadLiveSmartChannels();
  pendingSharePayload = { content, title, targetChannel: fetchedSmartChannels[0] || defaultSmartChannels[0] };
  
  const modal = document.getElementById("smartChannelPickerModal");
  const titleEl = document.getElementById("smartSnippetTitle");
  const contentEl = document.getElementById("smartSnippetContent");

  if (titleEl) titleEl.textContent = title;
  if (contentEl) contentEl.textContent = content;

  renderSmartChannelsList();
  if (modal) modal.hidden = false;
}

function renderSmartChannelsList() {
  const container = document.getElementById("smartChannelsList");
  const query = (document.getElementById("smartChannelFilter")?.value || "").toLowerCase();
  if (!container) return;

  const channelsToRender = fetchedSmartChannels.length ? fetchedSmartChannels : defaultSmartChannels;
  const filtered = channelsToRender.filter((c) => !query || (c.name || "").toLowerCase().includes(query) || (c.target || "").toLowerCase().includes(query));

  let htmlStr = "";

  if (state.slackConnected === false || state.discordConnected === false) {
    htmlStr += `<div class="security-badge bottom-space" style="font-size:11px;">
      <span>ℹ️</span>
      <div>
        <b>Messaging Integration Status:</b><br>
        ${!state.slackConnected ? 'Slack is not connected. <button data-action="connect-messaging-prompt" class="small-btn">Connect Slack</button><br>' : ''}
        ${!state.discordConnected ? 'Discord is not connected. <button data-action="connect-messaging-prompt" class="small-btn">Connect Discord</button>' : ''}
      </div>
    </div>`;
  }

  htmlStr += filtered.map((c, index) => {
    const isSelected = pendingSharePayload.targetChannel?.target === c.target && pendingSharePayload.targetChannel?.platform === c.platform;
    const icon = c.icon || (c.platform === "slack" ? "💬" : "🎮");
    return `<div class="smart-channel-pill ${isSelected ? "selected" : ""}" data-smart-channel-idx="${index}">
      <span>${icon}</span>
      <span>${escapeHtml(c.name || c.target)}</span>
    </div>`;
  }).join("") || '<div class="muted">No matching channels or users</div>';

  container.innerHTML = htmlStr;
}

  pendingSharePayload = { content, title, targetChannel: defaultSmartChannels[0] };
  const modal = document.getElementById("smartChannelPickerModal");
  const titleEl = document.getElementById("smartSnippetTitle");
  const contentEl = document.getElementById("smartSnippetContent");

  if (titleEl) titleEl.textContent = title;
  if (contentEl) contentEl.textContent = content;

  renderSmartChannelsList();
  if (modal) modal.hidden = false;
}

function renderSmartChannelsList() {
  const container = document.getElementById("smartChannelsList");
  const query = (document.getElementById("smartChannelFilter")?.value || "").toLowerCase();
  if (!container) return;

  const filtered = defaultSmartChannels.filter((c) => !query || c.name.toLowerCase().includes(query) || c.target.toLowerCase().includes(query));

  container.innerHTML = filtered.map((c, index) => {
    const isSelected = pendingSharePayload.targetChannel?.target === c.target && pendingSharePayload.targetChannel?.platform === c.platform;
    return `<div class="smart-channel-pill ${isSelected ? "selected" : ""}" data-smart-channel-idx="${index}">
      <span>${c.icon}</span>
      <span>${escapeHtml(c.name)}</span>
    </div>`;
  }).join("") || '<div class="muted">No matching channels</div>';
}

async function confirmShareSmartChannel() {
  if (!pendingSharePayload.targetChannel) return;
  const { platform, target } = pendingSharePayload.targetChannel;
  const content = pendingSharePayload.content;
  const modal = document.getElementById("smartChannelPickerModal");

  const commandName = platform === "slack" ? "send_slack_notification" : "send_discord_notification";
  const payload = platform === "slack"
    ? { message: `[${pendingSharePayload.title} -> #${target}]\n${content}` }
    : { content: `[${pendingSharePayload.title} -> #${target}]\n${content}` };

  await command(commandName, payload);
  if (modal) modal.hidden = true;
  await refreshEvents();
}


async function loginWithOAuth(provider = "slack") {
  const statusEl = document.getElementById("messagingStatus");
  if (statusEl) statusEl.textContent = `Opening official 1-Click ${provider.toUpperCase()} OAuth sign-in...`;
  try {
    const res = await command("get_oauth_url", { provider });
    if (res.ok && res.oauth_url) {
      window.open(res.oauth_url, "_blank", "width=600,height=750");
      if (statusEl) statusEl.textContent = `Opened official ${provider.toUpperCase()} authorization screen. Confirm in popup window.`;
    }
  } catch (err) {
    if (statusEl) statusEl.textContent = String(err);
  }
}

async function sendSlackMessage() {
  const url = (document.getElementById("slackWebhookInput")?.value || "").trim();
  const text = (document.getElementById("slackMessageInput")?.value || "").trim() || "Tech Connector test notification from mobile client";
  const statusEl = document.getElementById("messagingStatus");

  if (!url) {
    if (statusEl) statusEl.textContent = "Please enter a valid Slack Incoming Webhook URL.";
    return;
  }

  if (statusEl) statusEl.textContent = "Sending Slack notification...";
  try {
    const res = await command("send_slack_notification", { webhook_url: url, message: text });
    if (statusEl) statusEl.textContent = res.ok ? `Slack notification sent: ${res.message}` : `Slack error: ${res.message}`;
  } catch (err) {
    if (statusEl) statusEl.textContent = String(err);
  }
}

async function sendDiscordMessage() {
  const url = (document.getElementById("discordWebhookInput")?.value || "").trim();
  const username = (document.getElementById("discordUsernameInput")?.value || "Tech Connector").trim();
  const text = (document.getElementById("discordMessageInput")?.value || "").trim() || "Tech Connector test notification from mobile client";
  const statusEl = document.getElementById("messagingStatus");

  if (!url) {
    if (statusEl) statusEl.textContent = "Please enter a valid Discord Webhook URL.";
    return;
  }

  if (statusEl) statusEl.textContent = "Sending Discord notification...";
  try {
    const res = await command("send_discord_notification", { webhook_url: url, content: text, username });
    if (statusEl) statusEl.textContent = res.ok ? `Discord notification sent: ${res.message}` : `Discord error: ${res.message}`;
  } catch (err) {
    if (statusEl) statusEl.textContent = String(err);
  }
}

async function saveMessagingSettings() {
  const slackUrl = (document.getElementById("slackWebhookInput")?.value || "").trim();
  const discordUrl = (document.getElementById("discordWebhookInput")?.value || "").trim();
  const discordUser = (document.getElementById("discordUsernameInput")?.value || "Tech Connector").trim();
  const statusEl = document.getElementById("messagingStatus");

  if (statusEl) statusEl.textContent = "Saving Webhook settings...";
  const res = await command("save_messaging_settings", {
    slack_webhook_url: slackUrl,
    discord_webhook_url: discordUrl,
    notify_slack_enabled: Boolean(slackUrl),
    notify_discord_enabled: Boolean(discordUrl),
    discord_username: discordUser,
  });
  if (statusEl) statusEl.textContent = res.message || "Saved.";
}

async function loadMessagingSettings() {
  try {
    const data = await command("get_messaging_settings", {});
    if (data.ok) {
      if (document.getElementById("slackWebhookInput")) document.getElementById("slackWebhookInput").value = data.slack_webhook_url || "";
      if (document.getElementById("discordWebhookInput")) document.getElementById("discordWebhookInput").value = data.discord_webhook_url || "";
      if (document.getElementById("discordUsernameInput")) document.getElementById("discordUsernameInput").value = data.discord_username || "Tech Connector";
    }
  } catch (_e) {}
}

async function sendRemote2FA() {
  const email = (document.getElementById("remoteEmailInput")?.value || "").trim();
  const phone = (document.getElementById("remotePhoneInput")?.value || "").trim();
  const authMethod = document.getElementById("remoteAuthMethod")?.value || "email";
  const statusEl = document.getElementById("remoteRegStatus");

  if (!email && !phone) {
    if (statusEl) statusEl.textContent = "Please enter your Email address or Phone number.";
    return;
  }

  if (email) localStorage.aiStudioUserEmail = email;
  if (phone) localStorage.aiStudioUserPhone = phone;

  if (statusEl) statusEl.textContent = `Dispatching 2FA security code via ${authMethod.toUpperCase()}...`;
  try {
    const res = await command("register_remote_user", { email, phone, auth_method: authMethod });
    if (res.ok) {
      if (statusEl) statusEl.textContent = res.message || "2FA code sent!";
      switchPairTab("2fa");
      const p2faStatus = document.getElementById("twoFactorStatus");
      if (p2faStatus) p2faStatus.textContent = `Security code sent to ${res.recipient}. Enter the 6-digit PIN below:`;
    } else {
      if (statusEl) statusEl.textContent = res.error || "Failed to dispatch 2FA code.";
    }
  } catch (err) {
    if (statusEl) statusEl.textContent = String(err);
  }
}

async function verify2FAPIN() {
  const otpCode = getOtpCode();
  const statusEl = document.getElementById("twoFactorStatus");
  if (otpCode.length < 6) {
    if (statusEl) statusEl.textContent = "Please enter all 6 digits of your 2FA security code.";
    return;
  }
  if (statusEl) statusEl.textContent = "Verifying 2FA PIN...";
  try {
    const result = await command("verify_2fa_pin", { pin: otpCode, token: state.token });
    if (result.ok) {
      if (statusEl) statusEl.textContent = "2FA verified! Connecting to workstation...";
      setPaired(true);
      loadMessagingSettings(); refreshAll();
    } else {
      if (statusEl) statusEl.textContent = result.error || "Verification failed.";
    }
  } catch (err) {
    if (statusEl) statusEl.textContent = String(err);
  }
}

async function request2FAPIN() {
  const statusEl = document.getElementById("twoFactorStatus");
  if (statusEl) statusEl.textContent = "Requesting new 2FA PIN on workstation...";
  const res = await command("generate_2fa_pin", {});
  if (res.ok && statusEl) {
    statusEl.textContent = `New 2FA code generated on PC screen! (Expires in ${res.expires_in}s)`;
  }
}

function switchPairTab(tabName) {
  document.querySelectorAll(".pair-tab").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.tab === tabName);
  });
  document.getElementById("tabQR").hidden = tabName !== "qr";
  document.getElementById("tabAutoDetect").hidden = tabName !== "autodetect";
  document.getElementById("tabManual").hidden = tabName !== "manual";
  const p2fa = document.getElementById("twoFactorPanel"); if (p2fa) p2fa.hidden = tabName !== "2fa";
  const preg = document.getElementById("tabRemoteReg"); if (preg) preg.hidden = tabName !== "remote-reg";
}

async function autoDetectLAN() {
  const statusEl = document.getElementById("lanDetectStatus");
  if (statusEl) statusEl.textContent = "Scanning local network for Tech Connector workstation...";
  const candidates = [
    "http://127.0.0.1:8765",
    "http://localhost:8765",
    currentOrigin(),
  ];
  let found = false;
  for (const base of candidates) {
    if (!base) continue;
    try {
      const res = await fetch(`${base}/api/status`, { headers: { "X-AI-Studio-Token": state.token, "X-AI-Studio-Language": currentLang } });
      if (res.ok) {
        state.serverBase = base;
        localStorage.aiStudioRemoteServerBase = base;
        setPaired(true);
        if (statusEl) statusEl.textContent = `Connected to workstation at ${base}`;
        loadMessagingSettings(); refreshAll();
        found = true;
        break;
      }
    } catch (_err) {}
  }
  if (!found && statusEl) {
    statusEl.textContent = "No server found automatically. Open Tech Connector on PC and scan the QR code.";
  }
}

function unpairDevice() {
  state.token = "";
  state.serverBase = "";
  localStorage.removeItem("aiStudioRemoteToken");
  localStorage.removeItem("aiStudioRemoteServerBase");
  setPaired(false);
}

function savePairing(pairUrlOrToken) {
  const input = (pairUrlOrToken || "").trim();
  if (!input) return;
  try {
    if (input.startsWith("http://") || input.startsWith("https://")) {
      const url = new URL(input);
      const token = url.searchParams.get("token");
      if (token) state.token = token;
      state.serverBase = url.origin;
    } else {
      state.token = input;
    }
  } catch (_e) {
    state.token = input;
  }
  if (localStorage.aiStudioUserEmail && document.getElementById("remoteEmailInput")) document.getElementById("remoteEmailInput").value = localStorage.aiStudioUserEmail;
if (localStorage.aiStudioUserPhone && document.getElementById("remotePhoneInput")) document.getElementById("remotePhoneInput").value = localStorage.aiStudioUserPhone;
if (state.token) localStorage.aiStudioRemoteToken = state.token;
  if (state.serverBase) localStorage.aiStudioRemoteServerBase = state.serverBase;
  els.tokenInput.value = state.token;
  setPaired(Boolean(state.token));
  loadMessagingSettings(); refreshAll();
}

async function api(path, options = {}) {
  const headers = Object.assign({
    "X-AI-Studio-Token": state.token,
    "X-AI-Studio-Language": currentLang,
  }, options.headers || {});
  
  if (options.body && typeof options.body === "object" && !(options.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(options.body);
  }

  const response = await fetch(apiUrl(path), Object.assign({}, options, { headers }));
  if (response.status === 401) {
    setPaired(false);
    throw new Error("Invalid or missing connection token");
  }
  if (!response.ok) {
    const text = await response.text().catch(() => "");
    throw new Error(`API error (${response.status}): ${text}`);
  }
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    return response.json();
  }
  return response.text();
}

async function command(name, payload = {}) {
  return api("/api/command", {
    method: "POST",
    body: { command: name, payload: Object.assign({ language: currentLang }, payload || {}) },
  });
}

function renderNodeGraph() {
  if (!els.nodeContainer || !els.svgWireLayer) return;

  els.nodeContainer.innerHTML = graphState.nodes.map((node) => {
    const isSelected = node.id === graphState.selectedNodeId;
    const pkg = escapeHtml(node.package || node.host || "Utility");
    const statusClass = node.status || "idle";
    
    const paramsHtml = (node.params || []).map((p) => {
      const pName = escapeHtml(p.name);
      const pAnn = escapeHtml(p.annotation || "Any");
      return `<div class="node-port-row">
        <span class="port-pin data" data-pin-type="in" data-node-id="${node.id}" data-port-name="${pName}" title="Input: ${pAnn}"></span>
        <span>${pName} <span class="muted">:${pAnn}</span></span>
      </div>`;
    }).join("");

    const outputsHtml = (node.outputs || []).map((o) => {
      const oName = escapeHtml(o.name);
      const oAnn = escapeHtml(o.annotation || "Any");
      return `<div class="node-port-row">
        <span>${oName} <span class="muted">:${oAnn}</span></span>
        <span class="port-pin data" data-pin-type="out" data-node-id="${node.id}" data-port-name="${oName}" title="Output: ${oAnn}"></span>
      </div>`;
    }).join("");

    return `<div class="node-card-visual ${isSelected ? "selected" : ""} ${statusClass}" 
                 id="${node.id}" 
                 style="left:${node.x}px; top:${node.y}px;"
                 data-node-card="${node.id}">
      <div class="node-header" data-drag-handle="${node.id}">
        <span class="pkg-badge pkg-${pkg.toLowerCase()}">${pkg}</span>
        <span class="node-title">${escapeHtml(node.label)}</span>
      </div>
      <div class="node-body">
        <div class="node-ports-column inputs">
          <div class="node-port-row">
            <span class="port-pin flow" data-pin-type="flow-in" data-node-id="${node.id}" title="Flow In"></span>
            <span class="muted small">in</span>
          </div>
          ${paramsHtml}
        </div>
        <div class="node-ports-column outputs">
          <div class="node-port-row">
            <span class="muted small">out</span>
            <span class="port-pin flow" data-pin-type="flow-out" data-node-id="${node.id}" title="Flow Out"></span>
          </div>
          ${outputsHtml}
        </div>
      </div>
    </div>`;
  }).join("");

  renderGraphWires();
  renderInspector();
}

function renderGraphWires() {
  if (!els.svgWireLayer || !els.graphCanvasContainer) return;
  const paths = [];

  graphState.flow_links.forEach((link) => {
    const fromEl = document.querySelector(`[data-node-id="${link.from_node}"][data-pin-type="flow-out"]`);
    const toEl = document.querySelector(`[data-node-id="${link.to_node}"][data-pin-type="flow-in"]`);
    if (fromEl && toEl) {
      const p1 = getPinCenter(fromEl);
      const p2 = getPinCenter(toEl);
      paths.push(`<path class="wire-flow" d="${bezierPath(p1.x, p1.y, p2.x, p2.y)}"/>`);
    }
  });

  graphState.data_links.forEach((link) => {
    const fromEl = document.querySelector(`[data-node-id="${link.from_node}"][data-port-name="${link.from_port}"][data-pin-type="out"]`);
    const toEl = document.querySelector(`[data-node-id="${link.to_node}"][data-port-name="${link.to_port}"][data-pin-type="in"]`);
    if (fromEl && toEl) {
      const p1 = getPinCenter(fromEl);
      const p2 = getPinCenter(toEl);
      paths.push(`<path class="wire-data" d="${bezierPath(p1.x, p1.y, p2.x, p2.y)}"/>`);
    }
  });

  if (graphState.connectingPin && graphState.tempWireEnd) {
    const p1 = graphState.connectingPin;
    const p2 = graphState.tempWireEnd;
    const isFlow = p1.is_flow;
    paths.push(`<path class="${isFlow ? "wire-flow" : "wire-data"}" d="${bezierPath(p1.x, p1.y, p2.x, p2.y)}"/>`);
  }

  els.svgWireLayer.innerHTML = `
    <defs>
      <marker id="arrowData" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
        <path d="M 0 0 L 10 5 L 0 10 z" fill="#16f26a"/>
      </marker>
      <marker id="arrowFlow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
        <path d="M 0 0 L 10 5 L 0 10 z" fill="#1e9bff"/>
      </marker>
    </defs>
    ${paths.join("")}
  `;
}

function bezierPath(x1, y1, x2, y2) {
  const dx = Math.abs(x2 - x1) * 0.5;
  return `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`;
}

function getPinCenter(element) {
  const rect = element.getBoundingClientRect();
  const containerRect = els.graphCanvasContainer.getBoundingClientRect();
  return {
    x: (rect.left - containerRect.left + rect.width / 2) / state.scale,
    y: (rect.top - containerRect.top + rect.height / 2) / state.scale,
  };
}

function renderInspector() {
  if (!els.inspectorBody) return;
  const node = graphState.nodes.find((n) => n.id === graphState.selectedNodeId);
  if (!node) {
    els.inspectorNodeKind.textContent = "Select a node";
    els.inspectorBody.innerHTML = '<div class="muted center-text">Tap any node on the graph canvas to inspect attributes.</div>';
    return;
  }

  els.inspectorNodeKind.textContent = `${node.package || node.host || "Utility"} • ${node.type || "DCC Command"}`;
  
  const literals = node.literal_values || {};
  const paramsHtml = (node.params || []).map((param) => {
    const pName = escapeHtml(param.name);
    const pAnn = escapeHtml(param.annotation || "Any");
    const val = escapeHtml(literals[param.name] ?? "");
    return `<div class="inspector-field">
      <label>${pName} <span class="muted">(${pAnn})</span></label>
      <input value="${val}" data-inspector-param="${pName}" placeholder="${pAnn} value...">
    </div>`;
  }).join("") || '<div class="muted">No editable parameters</div>';

  els.inspectorBody.innerHTML = `
    <div class="inspector-form">
      <div class="inspector-field">
        <label>Node Name</label>
        <input value="${escapeHtml(node.label)}" data-inspector-field="label">
      </div>
      <div class="inspector-field">
        <label>Node Type</label>
        <select data-inspector-field="type">
          ${["Inspect", "Pipeline", "DCC Command", "Validate", "Report"].map((t) => `<option value="${t}" ${node.type === t ? "selected" : ""}>${t}</option>`).join("")}
        </select>
      </div>
      <div class="inspector-field">
        <label>Description / Detail</label>
        <textarea data-inspector-field="detail">${escapeHtml(node.detail || "")}</textarea>
      </div>
      <h4>Parameter Attributes</h4>
      ${paramsHtml}
      <div class="toolbar top-space">
        <button data-action="delete-selected-node" class="bad-btn">Remove Node</button>
      </div>
    </div>
  `;
}


let pendingRemoteExecutionPayload = null;

async function requestRemoteExecutionWith2FA(payload) {
  state.require2FAForRemoteRun = localStorage.aiStudioRequire2FAForRemoteRun !== "false";
  
  if (!state.require2FAForRemoteRun) {
    // User opted out of 2FA for remote runs -> execute instantly!
    await command("execute_workflow", payload);
    return;
  }

  // 2FA is required -> store payload and show 2FA Modal
  pendingRemoteExecutionPayload = payload;
  const modal = document.getElementById("remoteRun2FAModal");
  const pipelineNameEl = document.getElementById("execPipelineName");
  const recipientEl = document.getElementById("exec2FARecipient");
  const statusEl = document.getElementById("exec2FAStatus");

  if (pipelineNameEl) pipelineNameEl.textContent = payload.pipeline_id || graphState.name;
  const recipient = localStorage.aiStudioUserEmail || localStorage.aiStudioUserPhone || "your registered workstation";
  if (recipientEl) recipientEl.textContent = `Security PIN dispatched to ${recipient}`;
  if (statusEl) statusEl.textContent = "";

  // Trigger PIN generation
  await command("generate_2fa_pin", {});
  if (modal) modal.hidden = false;
}

async function confirmRemoteRun2FA() {
  const digits = Array.from(document.querySelectorAll(".exec-otp")).map((i) => i.value).join("");
  const statusEl = document.getElementById("exec2FAStatus");
  const optOutCheck = document.getElementById("optOut2FACheckbox");

  if (digits.length < 6) {
    if (statusEl) statusEl.textContent = "Please enter the 6-digit security code.";
    return;
  }

  if (statusEl) statusEl.textContent = "Verifying code...";
  const ver = await command("verify_2fa_pin", { pin: digits, token: state.token });
  if (ver.ok) {
    if (optOutCheck && optOutCheck.checked) {
      localStorage.aiStudioRequire2FAForRemoteRun = "false";
      state.require2FAForRemoteRun = false;
      const toggle = document.getElementById("require2FAForRemoteRunToggle");
      if (toggle) toggle.checked = false;
    }
    const modal = document.getElementById("remoteRun2FAModal");
    if (modal) modal.hidden = true;

    if (pendingRemoteExecutionPayload) {
      await command("execute_workflow", pendingRemoteExecutionPayload);
      pendingRemoteExecutionPayload = null;
    }
  } else {
    if (statusEl) statusEl.textContent = ver.error || "Verification failed.";
  }
}

function closeRemoteRun2FAModal() {
  const modal = document.getElementById("remoteRun2FAModal");
  if (modal) modal.hidden = true;
  pendingRemoteExecutionPayload = null;
}

async function runGraphRemotely() {
  const steps = graphState.nodes.map((node) => ({
    label: `${node.type || "Node"}: ${node.label || node.id}`,
    detail: node.detail || "",
    node_id: node.id,
    node_type: node.type || "DCC Command",
    literal_values: node.literal_values || {},
  }));
  await requestRemoteExecutionWith2FA({
    pipeline_id: graphState.pipeline_id || graphState.name,
    nodes: graphState.nodes,
    data_links: graphState.data_links,
    flow_links: graphState.flow_links,
    steps,
  });
}

async function saveGraphToWorkstation() {
  const result = await command("save_pipeline_graph", {
    pipeline_id: graphState.pipeline_id,
    name: graphState.name,
    host: graphState.host,
    goal: graphState.goal,
    nodes: graphState.nodes,
    data_links: graphState.data_links,
    flow_links: graphState.flow_links,
  });
  if (result.ok) {
    graphState.pipeline_id = result.pipeline_id || graphState.pipeline_id;
    await refreshPipelines();
  }
}

async function loadPipelineGraph(pipelineId) {
  const data = await api(`/api/pipeline-graph?pipeline_id=${encodeURIComponent(pipelineId)}`);
  if (!data.ok) return;
  graphState.pipeline_id = data.pipeline_id || pipelineId;
  graphState.name = data.name || "Loaded Pipeline";
  graphState.host = data.host || "general";
  graphState.goal = data.goal || "";
  graphState.nodes = data.nodes || [];
  graphState.data_links = data.data_links || [];
  graphState.flow_links = data.flow_links || [];
  graphState.selectedNodeId = graphState.nodes[0]?.id || "";
  renderNodeGraph();
}

function autoLayoutGraph() {
  graphState.nodes.forEach((node, index) => {
    node.x = 40 + (index % 3) * 260;
    node.y = 60 + Math.floor(index / 3) * 180;
  });
  renderNodeGraph();
}

function toggleSplitView() {
  graphState.splitViewActive = !graphState.splitViewActive;
  els.workspaceLayout.classList.toggle("split-active", graphState.splitViewActive);
  if (graphState.splitViewActive) refreshScreen(graphState.activeAppTarget);
}

async function openNodePalette() {
  els.nodePaletteModal.hidden = false;
  const data = await api("/api/node-catalog");
  graphState.catalog = data.catalog || [];
  renderCatalogList();
}

function renderCatalogList() {
  const query = (els.paletteFilter.value || "").toLowerCase();
  const pkgFilter = els.palettePackageFilter.value || "all";
  let items = graphState.catalog;
  if (query) {
    items = items.filter((item) => item.name.toLowerCase().includes(query) || item.detail.toLowerCase().includes(query));
  }
  if (pkgFilter !== "all") {
    items = items.filter((item) => (item.package || "").toLowerCase() === pkgFilter.toLowerCase());
  }
  els.paletteCatalogList.innerHTML = items.map((item, index) => {
    const pkg = escapeHtml(item.package || "Utility");
    return `<div class="row">
      <b>[${pkg}] ${escapeHtml(item.name)}</b> <span class="pill">${escapeHtml(item.type)}</span>
      <div>${escapeHtml(item.detail)}</div>
      <div class="toolbar top-space">
        <button data-add-catalog-item="${index}">Add to Graph</button>
      </div>
    </div>`;
  }).join("") || '<div class="muted">No matching nodes in catalog</div>';
}

function addCatalogItemToGraph(item) {
  const count = graphState.nodes.length + 1;
  const newNode = {
    id: `node_${Date.now()}_${count}`,
    label: item.name,
    package: item.package || "Utility",
    type: item.type || "DCC Command",
    detail: item.detail || "",
    params: item.params || [],
    outputs: item.outputs || [{ name: "result", annotation: "Any" }],
    literal_values: {},
    x: 60 + (graphState.nodes.length % 3) * 260,
    y: 60 + Math.floor(graphState.nodes.length / 3) * 180,
    status: "idle",
  };
  graphState.nodes.push(newNode);
  graphState.selectedNodeId = newNode.id;
  els.nodePaletteModal.hidden = true;
  renderNodeGraph();
}

async function refreshAll() {
  if (!state.token) {
    setPaired(false);
    return;
  }
  try {
    const status = await api("/api/status");
    state.status = status.status || {};
    setPaired(true);
    els.online.textContent = translateStatus("Online");
    els.online.classList.add("online");
    els.project.textContent = status.status.project || "No project";
    els.model.textContent = status.status.model || "No model";
    els.status.textContent = JSON.stringify(status.status, null, 2);
    await refreshApplications();
    await refreshScreen(graphState.activeAppTarget);
    await refreshJobs();
    await refreshPipelines();
    await refreshEvents();
  } catch (error) {
    els.online.textContent = translateStatus("Offline");
    els.online.classList.remove("online");
    els.status.textContent = String(error);
  }
}

async function refreshApplications() {
  const data = await api("/api/applications");
  state.applications = data.applications || [];
  els.applicationsList.innerHTML = state.applications.map((app, index) => `
    <div class="row">
      <b>${escapeHtml(app.name)}</b> <span class="pill">${escapeHtml(app.status)}</span>
      <div>${escapeHtml(app.id)}</div>
      <div class="toolbar top-space">
        <button data-monitor-app="${index}">Monitor</button>
        <button data-snapshot-app="${index}">Snapshot</button>
        <button data-screen-app="${index}">View Screen</button>
      </div>
    </div>
  `).join("") || '<div class="muted">No applications reported</div>';
}

const screenStreamState = {
  fps: 15,
  streamTimer: null,
  trackpadMode: false,
  cursorXPct: 0.5,
  cursorYPct: 0.5,
  isPointerDown: false,
  pointerStartX: 0,
  pointerStartY: 0,
  pressTimer: null,
  latencyMs: 0,
  frameCount: 0,
  fpsMeasured: 15,
  lastFpsCalc: Date.now(),
};

async function refreshScreen(applicationId = graphState.activeAppTarget || "desktop") {
  if (!els.screenImage || !state.token) return;
  graphState.activeAppTarget = applicationId;
  if (els.screenTargetBadgeText) els.screenTargetBadgeText.textContent = applicationId.toUpperCase();
  
  const start = performance.now();
  const stamp = Date.now();
  const imgUrl = apiUrl(`/api/screen.png?target=${encodeURIComponent(applicationId)}&token=${encodeURIComponent(state.token)}&t=${stamp}`);

  return new Promise((resolve) => {
    const tempImg = new Image();
    tempImg.onload = () => {
      els.screenImage.src = imgUrl;
      const end = performance.now();
      screenStreamState.latencyMs = Math.round(end - start);
      screenStreamState.frameCount++;
      
      const now = Date.now();
      if (now - screenStreamState.lastFpsCalc >= 1000) {
        screenStreamState.fpsMeasured = screenStreamState.frameCount;
        screenStreamState.frameCount = 0;
        screenStreamState.lastFpsCalc = now;
      }
      
      if (els.hudTelemetry) {
        els.hudTelemetry.textContent = `${screenStreamState.fpsMeasured} FPS • ${screenStreamState.latencyMs}ms`;
      }
      resolve();
    };
    tempImg.onerror = () => resolve();
    tempImg.src = imgUrl;
  });
}

function setStreamFps(fps) {
  screenStreamState.fps = Number(fps);
  if (screenStreamState.streamTimer) {
    clearInterval(screenStreamState.streamTimer);
    screenStreamState.streamTimer = null;
  }
  if (screenStreamState.fps > 0) {
    const intervalMs = Math.max(30, Math.round(1000 / screenStreamState.fps));
    screenStreamState.streamTimer = setInterval(() => {
      if (document.hidden) return;
      refreshScreen(graphState.activeAppTarget);
    }, intervalMs);
  }
}

async function sendDesktopInput(type, extras = {}) {
  try {
    await command("send_desktop_input", Object.assign({
      type,
      target: graphState.activeAppTarget,
      x_percent: screenStreamState.cursorXPct,
      y_percent: screenStreamState.cursorYPct,
    }, extras));
  } catch (_e) {}
}

function updateVirtualCursor() {
  if (!els.virtualCursor || !els.screenFrame) return;
  const rect = els.screenFrame.getBoundingClientRect();
  const px = screenStreamState.cursorXPct * rect.width;
  const py = screenStreamState.cursorYPct * rect.height;
  els.virtualCursor.style.left = `${px}px`;
  els.virtualCursor.style.top = `${py}px`;
}

function toggleTrackpadMode() {
  screenStreamState.trackpadMode = !screenStreamState.trackpadMode;
  if (els.screenFrame) els.screenFrame.classList.toggle("trackpad-active", screenStreamState.trackpadMode);
  if (els.virtualCursor) els.virtualCursor.hidden = !screenStreamState.trackpadMode;
  if (els.trackpadToggleBtn) els.trackpadToggleBtn.classList.toggle("primary-btn", screenStreamState.trackpadMode);
  if (els.controlModeStatus) {
    els.controlModeStatus.textContent = screenStreamState.trackpadMode ? "🖱️ Touchpad Trackpad Mode" : "Direct Touch Mode";
  }
  if (screenStreamState.trackpadMode) updateVirtualCursor();
}

function setupInteractiveScreenControls() {
  if (!els.screenFrame) return;

  const getImgRelPos = (evt) => {
    const rect = els.screenImage.getBoundingClientRect();
    const xPct = Math.max(0, Math.min(1, (evt.clientX - rect.left) / (rect.width || 1)));
    const yPct = Math.max(0, Math.min(1, (evt.clientY - rect.top) / (rect.height || 1)));
    return { xPct, yPct };
  };

  els.screenFrame.addEventListener("pointerdown", (evt) => {
    if (evt.target.closest(".dcc-toolbar-overlay") || evt.target.closest(".app-badge-overlay")) return;
    screenStreamState.isPointerDown = true;
    screenStreamState.pointerStartX = evt.clientX;
    screenStreamState.pointerStartY = evt.clientY;

    if (!screenStreamState.trackpadMode) {
      const pos = getImgRelPos(evt);
      screenStreamState.cursorXPct = pos.xPct;
      screenStreamState.cursorYPct = pos.yPct;
      sendDesktopInput("move");
    }

    screenStreamState.pressTimer = setTimeout(() => {
      if (screenStreamState.isPointerDown) {
        sendDesktopInput("right_click");
        screenStreamState.pressTimer = null;
      }
    }, 450);
  });

  els.screenFrame.addEventListener("pointermove", (evt) => {
    if (!screenStreamState.isPointerDown) return;

    if (screenStreamState.trackpadMode) {
      const rect = els.screenFrame.getBoundingClientRect();
      const dx = (evt.clientX - screenStreamState.pointerStartX) / (rect.width || 1);
      const dy = (evt.clientY - screenStreamState.pointerStartY) / (rect.height || 1);
      screenStreamState.pointerStartX = evt.clientX;
      screenStreamState.pointerStartY = evt.clientY;

      screenStreamState.cursorXPct = Math.max(0, Math.min(1, screenStreamState.cursorXPct + dx * 0.8));
      screenStreamState.cursorYPct = Math.max(0, Math.min(1, screenStreamState.cursorYPct + dy * 0.8));
      updateVirtualCursor();
      sendDesktopInput("move");
    } else {
      const pos = getImgRelPos(evt);
      screenStreamState.cursorXPct = pos.xPct;
      screenStreamState.cursorYPct = pos.yPct;
      sendDesktopInput("move");
    }
  });

  const endPointer = (evt) => {
    if (!screenStreamState.isPointerDown) return;
    screenStreamState.isPointerDown = false;
    if (screenStreamState.pressTimer) {
      clearTimeout(screenStreamState.pressTimer);
      screenStreamState.pressTimer = null;
      sendDesktopInput("click");
    }
  };

  els.screenFrame.addEventListener("pointerup", endPointer);
  els.screenFrame.addEventListener("pointercancel", endPointer);

  els.screenFrame.addEventListener("wheel", (evt) => {
    evt.preventDefault();
    const delta = evt.deltaY > 0 ? -120 : 120;
    sendDesktopInput("scroll", { delta_y: delta });
  }, { passive: false });
}

function handleDccCommand(dccCmd) {
  if (dccCmd === "orbit") sendDesktopInput("hotkey", { key: "LMB", modifiers: ["ALT"] });
  if (dccCmd === "focus") sendDesktopInput("key_press", { key: "F" });
  if (dccCmd === "translate") sendDesktopInput("key_press", { key: "W" });
  if (dccCmd === "rotate") sendDesktopInput("key_press", { key: "E" });
  if (dccCmd === "scale") sendDesktopInput("key_press", { key: "R" });
  if (dccCmd === "play") sendDesktopInput("key_press", { key: "SPACE" });
  if (dccCmd === "undo") sendDesktopInput("hotkey", { key: "Z", modifiers: ["CTRL"] });
  if (dccCmd === "redo") sendDesktopInput("hotkey", { key: "Y", modifiers: ["CTRL"] });
  if (dccCmd === "key") sendDesktopInput("key_press", { key: "S" });
}

function openVirtualKeyboardModal() {
  const m = document.getElementById("virtualKeyboardModal");
  if (m) m.hidden = false;
}

function closeVirtualKeyboardModal() {
  const m = document.getElementById("virtualKeyboardModal");
  if (m) m.hidden = true;
}

async function sendVirtualType() {
  const input = document.getElementById("virtualTextInput");
  const text = (input?.value || "").trim();
  if (!text) return;
  await sendDesktopInput("type_text", { text });
  if (input) input.value = "";
}

function toggleFullscreenScreen() {
  if (els.screenShareDrawer) {
    els.screenShareDrawer.classList.toggle("fullscreen");
  }
}

async function refreshJobs() {
  const data = await api("/api/jobs");
  state.activeJobs = data.active_jobs || [];
  state.finishedJobs = data.finished_jobs || [];
  
  els.activeJobsList.innerHTML = state.activeJobs.map((j, index) => renderJobCard("active", j, index)).join("") || `<div class="muted">${translateStatus("no_jobs")}</div>`;
  els.finishedJobsList.innerHTML = state.finishedJobs.map((j, index) => renderJobCard("finished", j, index)).join("") || `<div class="muted">${translateStatus("no_finished")}</div>`;
}

function renderJobCard(source, job, index) {
  return `<div class="row">
    <b>${escapeHtml(job.title)}</b> <span class="pill">${escapeHtml(translateStatus(job.status))}</span>
    <div class="muted small">${escapeHtml(job.job_id)}</div>
    <div>${escapeHtml(job.current_step || "")}</div>
    <div class="toolbar top-space">
      <button data-view-job="${source}:${index}">View Logs & Terminal</button>
    </div>
  </div>`;
}

async function refreshJobDetail(jobId) {
  const job = await api(`/api/job?job_id=${encodeURIComponent(jobId)}`);
  els.jobDetail.textContent = JSON.stringify(job, null, 2);
}

async function refreshPipelines() {
  const filter = (els.pipelineFilter.value || "").toLowerCase();
  const data = await api("/api/pipelines");
  state.pipelines = (data.pipelines || []).filter((p) => !filter || p.name.toLowerCase().includes(filter) || p.goal.toLowerCase().includes(filter));
  
  els.pipelinesList.innerHTML = state.pipelines.map((p, index) => `
    <div class="row">
      <b>${escapeHtml(p.name)}</b> <span class="pill">${escapeHtml(p.host || "General")}</span>
      <div>${escapeHtml(p.goal || "")}</div>
      <div class="toolbar top-space">
        <button data-open-pipeline-graph="${index}">Edit in Graph</button>
        <button data-run-pipeline="${index}">Run Remotely</button>
      </div>
    </div>
  `).join("") || '<div class="muted">No pipelines found</div>';
}

async function refreshEvents() {
  const data = await api("/api/events");
  state.events = data.events || [];
  els.eventsList.innerHTML = state.events.map((e) => `
    <div class="row">
      <b>${escapeHtml(e.event_type)}</b> <span class="pill">${escapeHtml(e.severity || "info")}</span>
      <div>${escapeHtml(e.message)} <button class="share-btn-badge" data-share-content="${escapeHtml(e.message)}" data-share-title="Event: ${escapeHtml(e.event_type)}">💬 Share to Channel</button></div>
      <div class="muted small">${new Date(e.timestamp * 1000).toLocaleTimeString()}</div>
    </div>
  `).join("") || `<div class="muted">${translateStatus("no_events")}</div>`;
}

async function submitPrompt() {
  const promptText = els.prompt.value.trim();
  if (!promptText) return;
  els.prompt.value = "";
  await command("continue_conversation", { prompt: promptText, language: currentLang });
  await refreshEvents();
}

function onClick(event) {
  const target = event.target.closest("button");
  if (!target) return;
  const action = target.dataset.action;
  const commandName = target.dataset.command;
  
  if (action === "change-stream-fps") setStreamFps(target.value);
  if (action === "toggle-trackpad-mode") toggleTrackpadMode();
  if (action === "open-virtual-keyboard") openVirtualKeyboardModal();
  if (action === "close-virtual-keyboard") closeVirtualKeyboardModal();
  if (action === "send-virtual-type") sendVirtualType();
  if (action === "toggle-fullscreen-screen") toggleFullscreenScreen();
  if (target.dataset.dccCmd) handleDccCommand(target.dataset.dccCmd);
  if (action === "send-key") sendDesktopInput("key_press", { key: target.dataset.key });
  if (action === "send-hotkey") sendDesktopInput("hotkey", { key: target.dataset.key, modifiers: [target.dataset.mod] });
  if (action === "change-app-target") {
    graphState.activeAppTarget = target.value;
    refreshScreen(target.value);
  }

  if (action === "change-lang") applyTranslations(target.value);
  if (action === "switch-pair-tab") switchPairTab(target.dataset.tab);
  if (action === "auto-detect-lan") autoDetectLAN();
  if (action === "confirm-share-smart-channel") confirmShareSmartChannel();
  if (action === "connect-messaging-prompt") { const m = document.getElementById("smartChannelPickerModal"); if (m) m.hidden = true; const msgPanel = document.querySelector('[data-menu="messaging"]'); if (msgPanel) msgPanel.scrollIntoView({ behavior: "smooth" }); }
  if (action === "close-smart-channel-modal") { const m = document.getElementById("smartChannelPickerModal"); if (m) m.hidden = true; }
  if (action === "oauth-login-slack") loginWithOAuth("slack");
  if (action === "oauth-login-discord") loginWithOAuth("discord");
  if (action === "oauth-login-atlassian") loginWithOAuth("atlassian");
  if (action === "oauth-login-clickup") loginWithOAuth("clickup");
  if (action === "send-slack-msg" || action === "test-slack-messaging") sendSlackMessage();
  if (action === "send-discord-msg" || action === "test-discord-messaging") sendDiscordMessage();
  if (action === "save-messaging-settings") saveMessagingSettings();
  if (action === "send-remote-2fa") sendRemote2FA();
  if (action === "verify-2fa") verify2FAPIN();
  if (action === "request-2fa-pin") request2FAPIN();
  if (action === "unpair-device") unpairDevice();
  if (action === "zoom-in") zoomBy(1.15);
  if (action === "zoom-out") zoomBy(0.85);
  if (action === "zoom-reset") zoomReset();
  if (action === "refresh") loadMessagingSettings(); refreshAll();
  if (action === "send-prompt") submitPrompt();
  if (action === "start-pairing") startPairing();
  if (action === "save-pair-url") savePairing(els.pairUrlInput.value);
  if (action === "install-app") installApp();
  if (action === "confirm-remote-run-2fa") confirmRemoteRun2FA();
  if (action === "close-remote-run-2fa") closeRemoteRun2FAModal();
  if (action === "run-graph") runGraphRemotely();
  if (action === "save-graph") saveGraphToWorkstation();
  if (action === "open-node-palette") openNodePalette();
  if (action === "close-node-palette") els.nodePaletteModal.hidden = true;
  if (action === "auto-layout-graph") autoLayoutGraph();
  if (action === "toggle-split-view") toggleSplitView();
  if (action === "clear-graph") {
    graphState.nodes = [];
    graphState.data_links = [];
    graphState.flow_links = [];
    graphState.selectedNodeId = "";
    renderNodeGraph();
  }
  if (action === "delete-selected-node") {
    if (graphState.selectedNodeId) {
      const id = graphState.selectedNodeId;
      graphState.nodes = graphState.nodes.filter((n) => n.id !== id);
      graphState.data_links = graphState.data_links.filter((l) => l.from_node !== id && l.to_node !== id);
      graphState.flow_links = graphState.flow_links.filter((l) => l.from_node !== id && l.to_node !== id);
      graphState.selectedNodeId = graphState.nodes[0]?.id || "";
      renderNodeGraph();
    }
  }
  if (target.dataset.addCatalogItem !== undefined) {
    const item = (graphState.catalog || [])[Number(target.dataset.addCatalogItem)];
    if (item) addCatalogItemToGraph(item);
  }
  if (target.dataset.openPipelineGraph !== undefined) {
    const pipeline = state.pipelines[Number(target.dataset.openPipelineGraph)];
    if (pipeline) loadPipelineGraph(pipeline.id);
  }
  if (target.dataset.runPipeline) {
    const pipeline = state.pipelines[Number(target.dataset.runPipeline)];
    if (pipeline) command("execute_workflow", { pipeline_id: pipeline.id, language: currentLang });
  }
  if (target.dataset.viewJob) {
    const [source, rawIndex] = target.dataset.viewJob.split(":");
    const list = source === "finished" ? state.finishedJobs : state.activeJobs;
    const job = list[Number(rawIndex)];
    if (job) refreshJobDetail(job.job_id);
  }
}

document.addEventListener("click", onClick);
document.addEventListener("change", (event) => {
  if (event.target.classList.contains("lang-select")) {
    applyTranslations(event.target.value);
  }
  if (event.target.id === "streamFpsSelect") {
    setStreamFps(event.target.value);
  }
  if (event.target.id === "appTargetSelect") {
    graphState.activeAppTarget = event.target.value;
    refreshScreen(event.target.value);
  }
});

document.addEventListener("pointerdown", (event) => {
  const pinEl = event.target.closest(".port-pin");
  if (pinEl) {
    const nodeId = pinEl.dataset.nodeId;
    const pinType = pinEl.dataset.pinType;
    const portName = pinEl.dataset.portName;
    const center = getPinCenter(pinEl);
    graphState.connectingPin = {
      node_id: nodeId,
      port_name: portName,
      pin_type: pinType,
      is_output: pinType === "out" || pinType === "flow-out",
      is_flow: pinType.includes("flow"),
      x: center.x,
      y: center.y,
    };
    graphState.tempWireEnd = { x: center.x, y: center.y };
    return;
  }

  const cardHeader = event.target.closest("[data-drag-handle]");
  if (cardHeader) {
    const nodeId = cardHeader.dataset.dragHandle;
    const node = graphState.nodes.find((n) => n.id === nodeId);
    if (node) {
      graphState.selectedNodeId = nodeId;
      graphState.draggingNodeId = nodeId;
      graphState.dragStartX = event.clientX;
      graphState.dragStartY = event.clientY;
      graphState.nodeStartX = node.x;
      graphState.nodeStartY = node.y;
      renderNodeGraph();
    }
    return;
  }

  const cardEl = event.target.closest("[data-node-card]");
  if (cardEl) {
    graphState.selectedNodeId = cardEl.dataset.nodeCard;
    renderNodeGraph();
  }
});

document.addEventListener("pointermove", (event) => {
  if (graphState.draggingNodeId) {
    const dx = (event.clientX - graphState.dragStartX) / state.scale;
    const dy = (event.clientY - graphState.dragStartY) / state.scale;
    const node = graphState.nodes.find((n) => n.id === graphState.draggingNodeId);
    if (node) {
      node.x = Math.max(0, graphState.nodeStartX + dx);
      node.y = Math.max(0, graphState.nodeStartY + dy);
      const cardEl = document.getElementById(node.id);
      if (cardEl) {
        cardEl.style.left = `${node.x}px`;
        cardEl.style.top = `${node.y}px`;
      }
      renderGraphWires();
    }
  }

  if (graphState.connectingPin && els.graphCanvasContainer) {
    const containerRect = els.graphCanvasContainer.getBoundingClientRect();
    graphState.tempWireEnd = {
      x: (event.clientX - containerRect.left) / state.scale,
      y: (event.clientY - containerRect.top) / state.scale,
    };
    renderGraphWires();
  }
});

document.addEventListener("pointerup", (event) => {
  if (graphState.connectingPin) {
    const targetPin = event.target.closest(".port-pin");
    if (targetPin) {
      const from = graphState.connectingPin;
      const toNodeId = targetPin.dataset.nodeId;
      const toPinType = targetPin.dataset.pinType;
      const toPortName = targetPin.dataset.portName;

      if (from.is_flow && toPinType.includes("flow") && from.node_id !== toNodeId) {
        graphState.flow_links.push({ from_node: from.node_id, to_node: toNodeId });
      } else if (!from.is_flow && from.is_output && toPinType === "in" && from.node_id !== toNodeId) {
        graphState.data_links.push({
          from_node: from.node_id,
          from_port: from.port_name,
          to_node: toNodeId,
          to_port: toPortName,
        });
      }
    }
    graphState.connectingPin = null;
    graphState.tempWireEnd = null;
    renderGraphWires();
  }
  graphState.draggingNodeId = null;
});

// Initialization
if (localStorage.aiStudioUserEmail && document.getElementById("remoteEmailInput")) document.getElementById("remoteEmailInput").value = localStorage.aiStudioUserEmail;
if (localStorage.aiStudioUserPhone && document.getElementById("remotePhoneInput")) document.getElementById("remotePhoneInput").value = localStorage.aiStudioUserPhone;
if (state.token) localStorage.aiStudioRemoteToken = state.token;
if (state.serverBase) localStorage.aiStudioRemoteServerBase = state.serverBase;
initSplashVideo();
applyZoom();
setPaired(Boolean(state.token && state.serverBase));
applyTranslations();
renderNodeGraph();
loadMessagingSettings(); refreshAll();
setupInteractiveScreenControls();
setStreamFps(15);
setInterval(refreshAll, 2500);


document.addEventListener("change", (event) => {
  if (event.target.id === "smartChannelFilter") renderSmartChannelsList();
  if (event.target.id === "require2FAForRemoteRunToggle") {
    localStorage.aiStudioRequire2FAForRemoteRun = event.target.checked ? "true" : "false";
    state.require2FAForRemoteRun = event.target.checked;
  }
});


document.addEventListener("input", (event) => {
  if (event.target.classList.contains("exec-otp")) {
    const idx = Number(event.target.dataset.execOtp);
    const val = event.target.value;
    if (val && idx < 5) {
      const next = document.querySelector(`[data-exec-otp="${idx + 1}"]`);
      if (next) next.focus();
    }
  }
});


document.addEventListener("click", (event) => {
  const pill = event.target.closest("[data-smart-channel-idx]");
  if (pill) {
    const idx = Number(pill.dataset.smartChannelIdx);
    const list = fetchedSmartChannels.length ? fetchedSmartChannels : defaultSmartChannels;
    pendingSharePayload.targetChannel = list[idx];
    renderSmartChannelsList();
  }
  const shareBtn = event.target.closest("[data-share-content]");
  if (shareBtn) {
    const content = shareBtn.dataset.shareContent;
    const title = shareBtn.dataset.shareTitle || "Shared Snippet";
    openSmartChannelPicker(content, title);
  }
});
