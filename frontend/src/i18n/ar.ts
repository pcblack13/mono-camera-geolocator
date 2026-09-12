/**
 * `i18n/ar.ts` — the Arabic of this app, keyed by its English.
 *
 * ★ TERMINOLOGY IS SURVEYING TERMINOLOGY, not word-for-word rendering. A few
 *   choices worth stating, because they recur everywhere:
 *
 *   - "Ground control point" → «نقطة ضبط أرضية» — the established surveying term,
 *     not a literal «نقطة تحكم».
 *   - "Landmark" → «معلَم» — what a surveyor points at in the photograph.
 *   - "Lookup table" → «جدول الإحداثيات» — literally "coordinates table". The
 *     literal «جدول البحث» is what a programmer hears; what this table DOES is give
 *     every pixel its latitude and longitude, and the Arabic says that.
 *   - "Detection" → «الكشف», "tracking" → «التعقّب», "frame" → «إطار».
 *   - Accuracy bands keep their plain words — «عالية / متوسطة / منخفضة» — because
 *     the surveyor is reading a judgement, not a category name.
 *
 * ★ Anything absent here renders in English rather than in a broken placeholder,
 *   so coverage grows sentence by sentence without ever leaving a blank screen.
 */

export const AR: Record<string, string> = {
  // ── the camera monitor: the map beside the picture, the drift watch in ⑤ ────
  'Satellite map': 'خريطة الأقمار الاصطناعية',
  'Display size': 'حجم العرض',
  'Ctrl + / Ctrl − / Ctrl 0': 'Ctrl + / Ctrl − / Ctrl 0',
  'Fit to screen': 'ملاءمة الشاشة',
  'this display': 'هذه الشاشة',
  'For a TV or a large monitor, pick a bigger size — every page, map and photograph scales together.':
    'لشاشة تلفاز أو شاشة كبيرة، اختر حجمًا أكبر — تتغيّر كل صفحة وخريطة وصورة معًا.',
  'Detect rate': 'معدّل الكشف',
  'Rate now': 'المعدّل الآن',
  'Rate, run average': 'المعدّل، متوسط التشغيل',
  'selected': 'المحدّد',
  'track': 'المسار',
  'Phase': 'المرحلة',
  'tracker': 'المتعقّب',
  'detector': 'الكاشف',
  'Open the map in its own window': 'افتح الخريطة في نافذة مستقلة',
  'The satellite map is open in its own window.':
    'خريطة الأقمار الاصطناعية مفتوحة في نافذة مستقلة.',
  'Bring it back': 'أعدها إلى هنا',
  'Back to the monitor': 'العودة إلى المراقبة',
  'No run yet — marks appear here the moment detection starts.':
    'لا يوجد تشغيل بعد — تظهر العلامات هنا فور بدء الكشف.',
  'The map window was blocked — allow pop-ups for this app and try again.':
    'مُنعت نافذة الخريطة — اسمح بالنوافذ المنبثقة لهذا التطبيق وحاول مجددًا.',
  'Resize the map': 'تغيير حجم الخريطة',
  'Dock the map below the video': 'ضع الخريطة أسفل الفيديو',
  'Place the map beside the video': 'ضع الخريطة بجانب الفيديو',
  'off — YOLO on every frame': 'متوقف — YOLO على كل إطار',
  'the tracker takes over from this frame': 'يتولى المتعقّب المهمة من هذا الإطار',
  'needs a lookup table (③)': 'يحتاج إلى جدول إحداثيات (③)',

  // ── the resume-session prompt and the home hero ───────────────────────────
  'Today': 'اليوم',
  'Yesterday': 'أمس',
  'You left one page open. Pick up where you stopped, or start with a clean workspace.':
    'تركت صفحة واحدة مفتوحة. تابع من حيث توقفت، أو ابدأ بمساحة عمل نظيفة.',
  'You left these pages open. Pick up where you stopped, or start with a clean workspace.':
    'تركت هذه الصفحات مفتوحة. تابع من حيث توقفت، أو ابدأ بمساحة عمل نظيفة.',
  'Restore session': 'استعادة الجلسة',
  'FIELD PHOTOGRAMMETRY · OFFLINE-FIRST': 'مسح تصويري ميداني · يعمل دون اتصال',
  // ── the shell: top bar and workspace navigation ───────────────────────────
  'Home': 'الرئيسية',
  'Dashboard': 'لوحة المعلومات',
  'Workspace': 'مساحة العمل',
  'Select a project': 'اختر مشروعًا',
  'Projects': 'المشاريع',
  'Recorded videos': 'الفيديوهات المسجّلة',
  'DEM processing': 'معالجة نموذج الارتفاع الرقمي',
  'GCP tables': 'جداول نقاط الضبط',
  'LUT generator': 'مولّد جدول الإحداثيات',
  'Live stream': 'البث المباشر',
  'Video detection': 'الكشف في الفيديو',
  'Project': 'المشروع',

  // ── language / theme switches ─────────────────────────────────────────────
  'Language': 'اللغة',
  'English': 'English',
  'Arabic': 'العربية',
  'Light theme': 'المظهر الفاتح',
  'Dark theme': 'المظهر الداكن',
  'System theme': 'مظهر النظام',

  // ── the detection pages ───────────────────────────────────────────────────
  'Run the detector over a clip from your video library. With a lookup table, every object found lands on the map at the spot where it stands — and the marks below export as CSV, GeoJSON or Shapefile.':
    'شغّل الكاشف على مقطع من مكتبة الفيديو لديك. مع جدول الإحداثيات، يظهر كل جسم يُعثر عليه على الخريطة في موضعه الحقيقي على الأرض — ويمكن تصدير العلامات أدناه بصيغة CSV أو GeoJSON أو Shapefile.',

  // the settings bar
  'SOURCE': 'المصدر',
  'DETECTOR': 'الكاشف',
  'PLACEMENT': 'التوطين',
  'TRACKING': 'التعقّب',
  'Source': 'المصدر',
  'Detector': 'الكاشف',
  'Placement': 'التوطين',
  'Tracking': 'التعقّب',
  'Video': 'الفيديو',
  'Upload': 'رفع',
  'Model': 'النموذج',
  'Detect': 'اكشف عن',
  'All classes': 'كل الأصناف',
  'Detail': 'مستوى التفاصيل',
  'Lookup table': 'جدول الإحداثيات',
  'Tracker': 'المتعقّب',
  'Start at frame': 'يبدأ عند الإطار',
  'Apply': 'تطبيق',
  'Start detection': 'ابدأ الكشف',
  'Starting…': 'جارٍ البدء…',
  'Pause': 'إيقاف مؤقت',
  'Resume': 'استئناف',
  'Restart': 'إعادة التشغيل',
  'Stop': 'إيقاف',
  'Running': 'قيد التشغيل',
  'Paused': 'متوقف مؤقتًا',
  'None': 'بلا',
  'Full (640 px)': 'كاملة (٦٤٠ بكسل)',
  'Balanced (480 px)': 'متوازنة (٤٨٠ بكسل)',
  'Fast (320 px)': 'سريعة (٣٢٠ بكسل)',
  'CSRT — accurate': 'CSRT — دقيق',
  'KCF — fast': 'KCF — سريع',
  'MIL — occlusion-tolerant': 'MIL — يتحمّل الحجب',
  'everything it can find': 'كل ما يستطيع العثور عليه',
  'only these': 'هذه فقط',
  'no marks on the map': 'لا علامات على الخريطة',
  'must match this camera': 'يجب أن يطابق هذه الكاميرا',
  'off — YOLO only': 'متوقف — YOLO فقط',
  'locks there': 'يثبّت عندها',
  'set a frame to use it': 'حدّد إطارًا لاستخدامه',
  'takes over there': 'يتولّى المهمة عندها',
  'unavailable': 'غير متاح',
  'needs opencv-contrib': 'يحتاج إلى opencv-contrib',
  'checking…': 'جارٍ الفحص…',
  'checking this machine…': 'جارٍ فحص هذا الجهاز…',
  'CPU — Balanced by default': 'المعالج — «متوازنة» افتراضيًا',
  'GPU': 'كرت الرسوميات',

  // the panels
  'Detected objects on the map': 'الأجسام المكتشفة على الخريطة',
  'Detected marks': 'العلامات المكتشفة',
  'Export': 'تصدير',
  'CSV': 'CSV',
  'GeoJSON': 'GeoJSON',
  'Shapefile': 'Shapefile',
  'Choose a video and press Start — the run streams here with its boxes.':
    'اختر فيديو واضغط «ابدأ» — سيُبَث التشغيل هنا مع مربعاته.',
  'Choose a video above — you can watch it here before detecting on it.':
    'اختر فيديو من الأعلى — يمكنك مشاهدته هنا قبل تشغيل الكشف عليه.',
  'Press Apply to watch this clip before detecting on it.':
    'اضغط «تطبيق» لمشاهدة هذا المقطع قبل تشغيل الكشف عليه.',
  'Choose a lookup table above and every detection lands here, on the ground.':
    'اختر جدول إحداثيات من الأعلى، وسيظهر كل كشف هنا في موضعه على الأرض.',
  'Without one the run still detects and counts — it just cannot say where.':
    'من دونه يظل التشغيل يكشف ويعدّ — لكنه لا يستطيع تحديد الموضع.',
  'Press Apply to open the map on this lookup table’s site.':
    'اضغط «تطبيق» لفتح الخريطة على موقع جدول الإحداثيات هذا.',
  'No marks yet — they appear here the moment a detected object lands on the map.':
    'لا علامات بعد — ستظهر هنا فور وصول أول جسم مكتشف إلى الخريطة.',
  'Your video library is empty — upload a clip to detect on.':
    'مكتبة الفيديو لديك فارغة — ارفع مقطعًا لتشغيل الكشف عليه.',

  // the attribute table
  'Class': 'الصنف',
  'Score': 'الدرجة',
  'Latitude': 'خط العرض',
  'Longitude': 'خط الطول',
  'Time (UTC)': 'الوقت (UTC)',
  'Date': 'التاريخ',
  'Local time': 'الوقت المحلي',
  'Frame': 'الإطار',
  'Camera': 'الكاميرا',
  'Camera location': 'موقع الكاميرا',

  // the run's own numbers
  'Detection': 'الكشف',
  'Device': 'الجهاز',
  'Algorithm': 'الخوارزمية',
  'Detected FPS': 'الإطارات في الثانية',
  'Frames detected': 'الإطارات المكشوفة',
  'Frames skipped': 'الإطارات المتخطّاة',
  'Marks placed': 'العلامات الموضوعة',
  'No terrain under feet': 'لا تضاريس تحت القدمين',
  'Oldest marks dropped': 'أقدم العلامات المُسقَطة',
  'YOLO every frame': 'YOLO في كل إطار',
  'CSRT tracking (locked)': 'تعقّب CSRT (مثبَّت)',
  'YOLO detecting': 'YOLO يكشف',

  // ── the live stream page ──────────────────────────────────────────────────
  'Stream statistics': 'إحصاءات البث',
  'FPS': 'الإطارات في الثانية',
  'Encoding': 'الترميز',
  'Resolution': 'الأبعاد',
  'Frames received': 'الإطارات المستلمة',
  'Uptime': 'مدة التشغيل',
  'Detected objects': 'الأجسام المكتشفة',
  'Capture frame': 'التقاط إطار',
  'Capturing…': 'جارٍ الالتقاط…',
  'Capture': 'التقاط',
  'Scan local devices': 'فحص الأجهزة المحلية',
  'Scan now': 'افحص الآن',
  'Name': 'الاسم',
  'Stream URL': 'رابط البث',
  'Add': 'إضافة',
  'Live captures': 'اللقطات المباشرة',
  'No device scanned yet': 'لم يُفحص أي جهاز بعد',
  'Device disconnected': 'انقطع الجهاز',
  'Stream disconnected': 'انقطع البث',
  'Retry measured mode': 'أعد المحاولة بالوضع المقيس',
  'not measurable': 'غير قابل للقياس',
  'unknown': 'غير معروف',
  'Full screen': 'ملء الشاشة',
  'Exit full screen': 'إنهاء ملء الشاشة',
  'Choose a device above to start the stream': 'اختر جهازًا من الأعلى لبدء البث',
  'No capture device found': 'لم يُعثر على جهاز التقاط',

  // ── marker colours ────────────────────────────────────────────────────────
  'Marker colours': 'ألوان العلامات',
  'Points on the photograph': 'النقاط على الصورة',
  'Points on the map': 'النقاط على الخريطة',
  'Suggestion boxes': 'مربعات الاقتراح',
  'By accuracy': 'حسب الدقة',
  'One colour': 'لون واحد',
  'Reset all to defaults': 'إعادة الكل إلى الإعدادات الافتراضية',
  'Every landmark and control point drawn on the photo.': 'كل معلَم ونقطة ضبط مرسومة على الصورة.',
  'Every control point pinned on the satellite map.':
    'كل نقطة ضبط مثبّتة على خريطة الأقمار الصناعية.',
  'Where the next point would help most.': 'حيث تفيد النقطة التالية أكثر ما يكون.',
  'Green → red shows how good each point is at a glance.':
    'التدرّج من الأخضر إلى الأحمر يبيّن جودة كل نقطة بنظرة واحدة.',
  'Colour this point': 'لوّن هذه النقطة',
  'Clear': 'مسح',

  // ── accuracy ──────────────────────────────────────────────────────────────
  'Measure error': 'قياس الخطأ',
  'Re-measure': 'إعادة القياس',
  'Measuring…': 'جارٍ القياس…',
  'Measure again': 'قياس مرة أخرى',
  'Defaults': 'الإعدادات الافتراضية',
  'Enough points': 'النقاط كافية',
  'Accuracy': 'الدقة',
  'high': 'عالية',
  'moderate': 'متوسطة',
  'low': 'منخفضة',
  'unreliable': 'غير موثوقة',

  // ── words that recur across the app ───────────────────────────────────────
  'Cancel': 'إلغاء',
  'Continue': 'متابعة',
  'Save': 'حفظ',
  'Delete': 'حذف',
  'Close': 'إغلاق',
  'Retry': 'إعادة المحاولة',
  'Loading…': 'جارٍ التحميل…',
  'marks': 'علامات',
  'Upload a video': 'رفع فيديو',

  // ── the rest of the app: projects, photographs, GCPs, DEM, map, video ─────
  '2D map': 'خريطة ثنائية الأبعاد',
  '3D terrain': 'تضاريس ثلاثية الأبعاد',
  'Account': 'الحساب',
  'Accuracy depends on your inputs': 'تعتمد الدقة على مدخلاتك',
  'Actual size': 'الحجم الفعلي',
  'Add from capture library': 'إضافة من مكتبة اللقطات',
  'Add from your capture library': 'إضافة من مكتبة اللقطات لديك',
  'Add image': 'إضافة صورة',
  'Adjust this GCP (A)': 'تعديل نقطة الضبط هذه (A)',
  'Adjusted': 'معدَّلة',
  'Adjustment note (optional)': 'ملاحظة التعديل (اختياري)',
  'All changes saved': 'حُفظت كل التغييرات',
  'All projects…': 'كل المشاريع…',
  'Annotate': 'التوصيف',
  'Annotation tools': 'أدوات التوصيف',
  'Apply elevations from the file': 'تطبيق الارتفاعات من الملف',
  'Apply this DEM to': 'تطبيق نموذج الارتفاع هذا على',
  'Area of interest': 'منطقة الاهتمام',
  'Auto GCP picking': 'انتقاء نقاط الضبط تلقائيًا',
  'Automatic caching': 'التخزين المؤقت التلقائي',
  'Automatic imagery caching status': 'حالة التخزين المؤقت التلقائي للصور',
  'Back': 'رجوع',
  'Back to projects': 'العودة إلى المشاريع',
  'Back to the default colour': 'العودة إلى اللون الافتراضي',
  'Back to workspace': 'العودة إلى مساحة العمل',
  'Basemap': 'خريطة الأساس',
  'Brightness': 'السطوع',
  'Brightness & contrast': 'السطوع والتباين',
  'Brightness and contrast': 'السطوع والتباين',
  'Browse files': 'تصفّح الملفات',
  'Build LUT': 'بناء جدول الإحداثيات',
  'Builds this session': 'عمليات البناء في هذه الجلسة',
  'Built (UTC)': 'بُني (UTC)',
  'Built on the adopted': 'بُني على المعتمَد',
  'CE90': 'CE90',
  'Cache an area for offline use': 'خزِّن منطقة للاستخدام دون اتصال',
  'Camera Intrinsics & Position': 'مُعامِلات الكاميرا الداخلية وموضعها',
  'Camera latitude': 'خط عرض الكاميرا',
  'Camera longitude': 'خط طول الكاميرا',
  'Camera offset (m)': 'إزاحة الكاميرا (م)',
  'Change': 'تغيير',
  'Change resolution': 'تغيير الدقة',
  'Choose .kml or .kmz': 'اختر ملف ‎.kml أو ‎.kmz',
  'Choose a different photo': 'اختر صورة أخرى',
  "Clear this point's colour": 'مسح لون هذه النقطة',
  'Close version history': 'إغلاق سجل النسخ',
  'Comparing two measurements': 'مقارنة قياسين',
  'Confidence': 'الثقة',
  'Confidence floor': 'الحد الأدنى للثقة',
  'Contrast': 'التباين',
  'Control points': 'نقاط الضبط',
  'Control points in this project will record': 'ستُسجَّل نقاط الضبط في هذا المشروع',
  'Coordinate format': 'صيغة الإحداثيات',
  'Coordinate reference system': 'نظام الإحداثيات المرجعي',
  'Coordinate system': 'نظام الإحداثيات',
  'Corrected median': 'الوسيط المصحَّح',
  'Could not load ground control points.': 'تعذّر تحميل نقاط الضبط الأرضية.',
  'Could not load projects': 'تعذّر تحميل المشاريع',
  'Could not load videos': 'تعذّر تحميل الفيديوهات',
  'Could not read the DEM library.': 'تعذّرت قراءة مكتبة نماذج الارتفاع.',
  'Could not read the capture library.': 'تعذّرت قراءة مكتبة اللقطات.',
  'Coverage': 'التغطية',
  'Create your first survey project': 'أنشئ أول مشروع مسح لك',
  'Cropped to AOI': 'مقتصّ على منطقة الاهتمام',
  'Current (lat, lon)': 'الحالي (عرض، طول)',
  'DEM loaded': 'حُمِّل نموذج الارتفاع',
  'DISCONNECTED': 'منقطع',
  'Decimal degrees': 'درجات عشرية',
  'Degrees / minutes / seconds': 'درجات / دقائق / ثوانٍ',
  'Delete from the library': 'حذف من المكتبة',
  'Delete photo': 'حذف الصورة',
  'Delete project': 'حذف المشروع',
  'Delete this DEM from the library?': 'حذف نموذج الارتفاع هذا من المكتبة؟',
  'Delete this GCP (Del)': 'حذف نقطة الضبط هذه (Del)',
  'Delete this ground control point?': 'حذف نقطة الضبط الأرضية هذه؟',
  'Delete this photo': 'حذف هذه الصورة',
  'Delete this photo?': 'حذف هذه الصورة؟',
  'Delete this photograph?': 'حذف هذه الصورة؟',
  'Delete this project?': 'حذف هذا المشروع؟',
  'Description (optional)': 'وصف (اختياري)',
  'Digital Elevation Model': 'نموذج الارتفاع الرقمي',
  'Done': 'تم',
  'Download .zip': 'تنزيل ‎.zip',
  'Drag a DEM file here, or click to browse': 'اسحب ملف نموذج ارتفاع إلى هنا، أو انقر للتصفّح',
  'Drop a field photograph here, or': 'أفلِت صورة ميدانية هنا، أو',
  'EXIF GPS present': 'بيانات GPS متوفرة في EXIF',
  'Edit': 'تعديل',
  'Edit settings': 'تعديل الإعدادات',
  'Edit the name': 'تعديل الاسم',
  "Edit this point's name": 'تعديل اسم هذه النقطة',
  'Edited after placement': 'عُدّلت بعد الوضع',
  'Elevation': 'الارتفاع',
  'Elevation (Z)': 'الارتفاع (Z)',
  'Elevation range': 'مدى الارتفاع',
  'Elevation source (DEM)': 'مصدر الارتفاع (DEM)',
  'Error measurement': 'قياس الخطأ',
  'Error measurement settings': 'إعدادات قياس الخطأ',
  'Fit to view': 'ملاءمة العرض',
  'Fit to view (F)': 'ملاءمة العرض (F)',
  'Four corners': 'الأركان الأربعة',
  'Frames': 'الإطارات',
  'Frames per step': 'الإطارات لكل خطوة',
  'Frames stopped arriving from': 'توقّفت الإطارات عن الوصول من',
  'From file': 'من ملف',
  'From library': 'من المكتبة',
  'GCP picking mode': 'وضع انتقاء نقاط الضبط',
  'GCP tables across all projects': 'جداول نقاط الضبط في كل المشاريع',
  'GCPs': 'نقاط الضبط',
  'GCPs must be accurate with low error': 'يجب أن تكون نقاط الضبط دقيقة وبخطأ منخفض',
  'Generated LUT bundles': 'حِزم جداول الإحداثيات المولَّدة',
  'Go to a location': 'الانتقال إلى موقع',
  'Go to location': 'الانتقال إلى موقع',
  'Go to second': 'الانتقال إلى الثانية',
  'Ground Control Points': 'نقاط الضبط الأرضية',
  'Ground control points': 'نقاط الضبط الأرضية',
  'Ground sample distance': 'مسافة العيّنة الأرضية',
  'Has GPS': 'يحتوي على GPS',
  'Heat map history': 'سجل خريطة الحرارة',
  'Height': 'الارتفاع',
  'How it works': 'كيف يعمل',
  'How many to rank:': 'كم عددًا يُرتَّب:',
  'How this works': 'كيف يعمل هذا',
  'Image': 'الصورة',
  'Image X': 'الصورة X',
  'Image Y': 'الصورة Y',
  'Image height (px)': 'ارتفاع الصورة (بكسل)',
  'Image setup': 'إعداد الصورة',
  'Image setup — camera, position, tilt': 'إعداد الصورة — الكاميرا والموضع والميل',
  'Image width (px)': 'عرض الصورة (بكسل)',
  'Imagery provider': 'مزوّد الصور',
  'Import': 'استيراد',
  'Import GCP positions from KML/KMZ': 'استيراد مواضع نقاط الضبط من KML/KMZ',
  'Import GCPs onto this photo': 'استيراد نقاط الضبط إلى هذه الصورة',
  'Import parameters': 'مُعامِلات الاستيراد',
  'Include in export': 'تضمين في التصدير',
  'Include map': 'تضمين الخريطة',
  'Include photo': 'تضمين الصورة',
  'Keep it': 'الإبقاء عليه',
  'Kind': 'النوع',
  'LUT library': 'مكتبة جداول الإحداثيات',
  'Landmark suggestions': 'اقتراحات المعالم',
  'Landmarks': 'المعالم',
  'Latitude (°)': 'خط العرض (°)',
  'Link to satellite map': 'الربط بخريطة الأقمار الصناعية',
  'Loading': 'جارٍ التحميل',
  'Loading ground control points': 'جارٍ تحميل نقاط الضبط الأرضية',
  'Loading the frame at the new position': 'جارٍ تحميل الإطار عند الموضع الجديد',
  'Longitude (°)': 'خط الطول (°)',
  'Main': 'الرئيسية',
  'Manual': 'يدوي',
  'Manual GCP picking': 'انتقاء نقاط الضبط يدويًا',
  'Manually adjusted': 'عُدّلت يدويًا',
  'Map (WGS84)': 'الخريطة (WGS84)',
  'Map imagery': 'صور الخريطة',
  'Map settings': 'إعدادات الخريطة',
  'Map settings — imagery and basemap': 'إعدادات الخريطة — الصور وخريطة الأساس',
  'Map view mode': 'وضع عرض الخريطة',
  'Marker certainty': 'يقين العلامة',
  'Menu': 'القائمة',
  'Name this photo': 'سمِّ هذه الصورة',
  'New GCP correspondence': 'تناظر جديد لنقطة ضبط',
  'New project': 'مشروع جديد',
  'New project for this video': 'مشروع جديد لهذا الفيديو',
  'New project name': 'اسم المشروع الجديد',
  'New survey project': 'مشروع مسح جديد',
  'No EXIF GPS': 'لا توجد بيانات GPS في EXIF',
  'No GCP tables yet': 'لا جداول نقاط ضبط بعد',
  'No elevation source': 'لا مصدر للارتفاع',
  'No ground control points yet': 'لا نقاط ضبط أرضية بعد',
  'No preview available at this second.': 'لا معاينة متاحة عند هذه الثانية.',
  'No project': 'لا يوجد مشروع',
  'No project selected': 'لم يُختَر أي مشروع',
  'No project selected.': 'لم يُختَر أي مشروع.',
  'No video selected': 'لم يُختَر فيديو',
  'No videos yet': 'لا فيديوهات بعد',
  'Note (optional)': 'ملاحظة (اختياري)',
  'Notes': 'ملاحظات',
  'Nothing importable in this file.': 'لا شيء قابل للاستيراد في هذا الملف.',
  'Number of suggested regions': 'عدد المناطق المقترحة',
  'Offline area': 'منطقة دون اتصال',
  'Offline cache': 'التخزين المؤقت دون اتصال',
  'Open in project': 'فتح داخل المشروع',
  'Open navigation menu': 'فتح قائمة التنقّل',
  'Open project': 'فتح المشروع',
  'Open scrub & capture': 'فتح التمرير والالتقاط',
  'Open the Workspace': 'افتح مساحة العمل',
  'Open Projects': 'افتح المشاريع',
  'Open the map': 'فتح الخريطة',
  'Output coordinate reference system': 'نظام الإحداثيات المرجعي للمُخرَج',
  'Output size': 'حجم المُخرَج',
  'Overview': 'نظرة عامة',
  'Page not found': 'الصفحة غير موجودة',
  'Payload': 'الحمولة',
  'Photo name': 'اسم الصورة',
  'Photo pixel': 'بكسل الصورة',
  'Photograph': 'الصورة',
  'Pixel X': 'البكسل X',
  'Pixel Y': 'البكسل Y',
  'Point': 'نقطة',
  'Point ID': 'معرّف النقطة',
  'Points of this GCP table': 'نقاط جدول الضبط هذا',
  'Process': 'معالجة',
  'Processed DEM library': 'مكتبة نماذج الارتفاع المعالَجة',
  'Processing complete': 'اكتملت المعالجة',
  'Processing for': 'معالجة من أجل',
  'Project details': 'تفاصيل المشروع',
  'Project name': 'اسم المشروع',
  'Project settings': 'إعدادات المشروع',
  'REFUSED': 'مرفوض',
  'Radius (m)': 'نصف القطر (م)',
  'Raw measured median': 'الوسيط المقيس الخام',
  'Re-open GCP to adjust': 'إعادة فتح نقطة الضبط للتعديل',
  'Re-open to adjust': 'إعادة الفتح للتعديل',
  'Reconnect': 'إعادة الاتصال',
  'Redraw': 'إعادة الرسم',
  'Remove': 'إزالة',
  'Rename project': 'إعادة تسمية المشروع',
  'Replace this photograph?': 'استبدال هذه الصورة؟',
  'Replace with another photo': 'الاستبدال بصورة أخرى',
  'Report title': 'عنوان التقرير',
  'Reset brightness and contrast': 'إعادة ضبط السطوع والتباين',
  'Reset process': 'إعادة ضبط المعالجة',
  'Reset to original': 'العودة إلى الأصل',
  'Retry failed': 'فشلت إعادة المحاولة',
  'Return to working draft': 'العودة إلى المسودة قيد العمل',
  'Satellite imagery is failing': 'صور الأقمار الصناعية تتعطّل',
  'Satellite imagery is unavailable —': 'صور الأقمار الصناعية غير متاحة —',
  'Save & open project': 'حفظ وفتح المشروع',
  'Scale': 'المقياس',
  'Search a place, e.g. Yammouneh': 'ابحث عن مكان، مثل يمّونة',
  'Seek video position': 'تحديد موضع الفيديو',
  'Set up this project’s map': 'إعداد خريطة هذا المشروع',
  'Settings saved before': 'حُفظت الإعدادات قبل',
  'Site name': 'اسم الموقع',
  'Skip export': 'تخطّي التصدير',
  'Skip for now': 'تخطَّ الآن',
  'Something went wrong': 'حدث خطأ ما',
  'Sort by': 'ترتيب حسب',
  'Stale coordinate': 'إحداثي قديم',
  'Straight to the Workspace': 'مباشرة إلى مساحة العمل',
  'Suggestion box colour': 'لون مربع الاقتراح',
  'Target project': 'المشروع الهدف',
  'Terms': 'الشروط',
  'The GCP overview could not be loaded.': 'تعذّر تحميل نظرة عامة على نقاط الضبط.',
  'The frame at': 'الإطار عند',
  'The whole project (every image)': 'المشروع بأكمله (كل صورة)',
  'This editor hit a problem': 'واجه هذا المحرر مشكلة',
  'This image could not be loaded.': 'تعذّر تحميل هذه الصورة.',
  'This image overrides the project DEM.': 'تتجاوز هذه الصورة نموذج ارتفاع المشروع.',
  'This page needs a project in its URL.': 'تحتاج هذه الصفحة إلى مشروع في رابطها.',
  'This photo has no embedded GPS.': 'لا تحتوي هذه الصورة على بيانات GPS مضمّنة.',
  'This photograph isn’t here': 'هذه الصورة غير موجودة',
  "This point's colour": 'لون هذه النقطة',
  'This project has no images yet': 'لا صور في هذا المشروع بعد',
  'This provider cannot be pre-cached.': 'لا يمكن التخزين المسبق لهذا المزوّد.',
  'This source could not be opened': 'تعذّر فتح هذا المصدر',
  'This table’s points could not be loaded.': 'تعذّر تحميل نقاط هذا الجدول.',
  'This video isn’t available': 'هذا الفيديو غير متاح',
  'Tiles locked': 'البلاطات المثبّتة',
  'Tilt below horizontal (°)': 'الميل تحت الأفقي (°)',
  'To colour': 'للتلوين',
  'Tolerance (% padding)': 'التسامح (% حشو)',
  'Try again': 'حاول مرة أخرى',
  'Undo last point': 'تراجع عن آخر نقطة',
  'Unselect project': 'إلغاء اختيار المشروع',
  'Upload DEM': 'رفع نموذج الارتفاع',
  'Upload a field video': 'رفع فيديو ميداني',
  'Upload a photo with a chosen resolution': 'رفع صورة بدقة محدّدة',
  'Upload field photographs': 'رفع صور ميدانية',
  'Upload video': 'رفع فيديو',
  'Uploaded': 'مرفوع',
  'Use a processed DEM': 'استخدام نموذج ارتفاع معالَج',
  'Use a processed DEM for this image': 'استخدام نموذج ارتفاع معالَج لهذه الصورة',
  'Use project DEM': 'استخدام نموذج ارتفاع المشروع',
  'Validation': 'التحقّق',
  'Version history': 'سجل النسخ',
  'Vertical exaggeration': 'المبالغة الرأسية',
  'Video upload progress': 'تقدّم رفع الفيديو',
  'What this survey covers, where, and when.': 'ما الذي يغطيه هذا المسح، وأين، ومتى.',
  'Whole DEM (no crop)': 'نموذج الارتفاع كاملًا (بلا اقتصاص)',
  'Width': 'العرض',
  'Worst accuracy': 'أسوأ دقة',
  'Zone or place name': 'اسم المنطقة أو المكان',
  'Zoom': 'التكبير',
  'Zoom in': 'تكبير',
  'Zoom in (+)': 'تكبير (+)',
  'Zoom out': 'تصغير',
  'Zoom out (−)': 'تصغير (−)',
  'auto UTM': 'UTM تلقائي',
  'clamped to tile edge': 'مُقيَّد بحافة البلاطة',
  'connecting…': 'جارٍ الاتصال…',
  'current': 'الحالي',
  'e.g. 12.5 or 0:12': 'مثال: 12.5 أو 0:12',
  'failed': 'فشل',
  'ground control points': 'نقاط الضبط الأرضية',

  // ── the guidance prose: what the app tells the surveyor to do ─────────────
  ', which applies them and runs.': '، الذي يطبّقها ويشغّلها.',
  '. Attach a DEM below to override it for this photo only.':
    '. أرفِق نموذج ارتفاع أدناه لتجاوزه لهذه الصورة فقط.',
  '. This is not a delay — the video has stopped. Reconnect the device (or check the camera) and press Reconnect.':
    '. هذا ليس تأخيرًا — فقد توقّف الفيديو. أعِد توصيل الجهاز (أو تحقّق من الكاميرا) ثم اضغط «إعادة الاتصال».',
  'A photograph’s table appears here after its first ground control point is committed in the editor.':
    'يظهر جدول الصورة هنا بعد تثبيت أول نقطة ضبط أرضية لها في المحرر.',
  'Accuracy is derived (CE90) — never invented': 'الدقة مُشتقّة (CE90) — وليست مُختلَقة',
  'Add a stream URL above, or scan for local devices, to enable the player. On a Raspberry Pi,':
    'أضِف رابط بث في الأعلى، أو افحص الأجهزة المحلية، لتفعيل المشغّل. على Raspberry Pi،',
  'All in': 'الكل في',
  'An import only moves points that already exist.': 'الاستيراد ينقل فقط النقاط الموجودة أصلًا.',
  'Attach the DEM': 'أرفِق نموذج الارتفاع',
  'Back to project': 'العودة إلى المشروع',
  'Beyond ±84° latitude UTM is undefined — this position needs a polar (UPS) grid.':
    'خارج خط العرض ±٨٤° يكون UTM غير معرّف — يحتاج هذا الموضع إلى شبكة قطبية (UPS).',
  'Building corner': 'ركن مبنى',
  'By default this photo uses the': 'تستخدم هذه الصورة افتراضيًا',
  'Camera position + radius': 'موضع الكاميرا + نصف القطر',
  'Cancelling…': 'جارٍ الإلغاء…',
  'Changing this clears the current measurement.': 'تغيير هذا يمسح القياس الحالي.',
  'Choose replacement…': 'اختر البديل…',
  'Coarse-to-fine sub-tiles — recovers local detail a full tile averages away':
    'بلاطات فرعية من الخشن إلى الدقيق — تستعيد التفاصيل المحلية التي تُذيبها البلاطة الكاملة',
  'Create a project': 'أنشئ مشروعًا',
  'Create project': 'إنشاء مشروع',
  'Crop a DEM to your area of interest and reproject it into metres, then export the result as a GeoTIFF.':
    'اقتصّ نموذج الارتفاع على منطقة اهتمامك وأعِد إسقاطه بالأمتار، ثم صدِّر النتيجة بصيغة GeoTIFF.',
  'DD + UTM + Z': 'DD + UTM + Z',
  'Each measurement is kept. Pick one to compare it with the run before it.':
    'يُحفَظ كل قياس. اختر واحدًا لمقارنته بالتشغيل الذي سبقه.',
  'Estimates are labelled as estimates, with their diagnostics':
    'التقديرات تُوسَم بأنها تقديرات، مع بياناتها التشخيصية',
  'Estimating…': 'جارٍ التقدير…',
  'Export expired': 'انتهت صلاحية التصدير',
  'Export not ready': 'التصدير غير جاهز',
  'Export those coordinates first if you still need them.':
    'صدِّر تلك الإحداثيات أولًا إن كنت لا تزال بحاجة إليها.',
  'Field corner': 'ركن حقل',
  'File too large': 'الملف كبير جدًا',
  'Flat, north-up map. Shows GCP markers, the offline cache and the image footprint — this is the pane GCP pairing runs in.':
    'خريطة مسطّحة باتجاه الشمال. تعرض علامات نقاط الضبط والتخزين المؤقت دون اتصال وبصمة الصورة — وهي اللوحة التي يجري فيها اقتران نقاط الضبط.',
  'From DEM library…': 'من مكتبة نماذج الارتفاع…',
  'Fully offline-capable — your own imagery and DEMs':
    'قادر على العمل دون اتصال بالكامل — بصورك ونماذج ارتفاعك',
  'Ground control points from field photographs — real coordinates, real elevations, and an honest accuracy figure on every point. Runs locally, works fully offline.':
    'نقاط ضبط أرضية من الصور الميدانية — إحداثيات حقيقية وارتفاعات حقيقية ورقم دقة صادق لكل نقطة. يعمل محليًا وبلا اتصال بالكامل.',
  'HDMI capture cards and USB/USB-C cameras plugged into this machine.':
    'بطاقات التقاط HDMI وكاميرات USB/USB-C الموصولة بهذا الجهاز.',
  'Import calibration CSV…': 'استيراد ملف المعايرة CSV…',
  'Irrigation canal': 'قناة ري',
  'Kept with your workspace on this computer. They change how marks are drawn, never the survey itself.':
    'تُحفَظ مع مساحة عملك على هذا الحاسوب. تغيّر طريقة رسم العلامات فقط، لا المسح نفسه.',
  'Large search areas take longer. Narrowing the location hint speeds this up considerably.':
    'مناطق البحث الكبيرة تستغرق وقتًا أطول. تضييق تلميح الموقع يسرّع ذلك كثيرًا.',
  'Loading ground control points…': 'جارٍ تحميل نقاط الضبط الأرضية…',
  'Loading ground control point…': 'جارٍ تحميل نقطة الضبط الأرضية…',
  'Loading history…': 'جارٍ تحميل السجل…',
  'Loading the 3D terrain view…': 'جارٍ تحميل عرض التضاريس ثلاثي الأبعاد…',
  'Locate points': 'حدِّد النقاط',
  'Manage the project DEM →': 'إدارة نموذج ارتفاع المشروع ←',
  'Most photographs': 'معظم الصور',
  'Mutual-information second chance — rescues tiles the basemap shows in a different season':
    'فرصة ثانية بالمعلومات المتبادلة — تنقذ البلاطات التي تعرضها خريطة الأساس في موسم مختلف',
  'Name (A–Z)': 'الاسم (أ–ي)',
  'Name (Z–A)': 'الاسم (ي–أ)',
  'Newest first': 'الأحدث أولًا',
  'No LUT bundles yet. Each build writes': 'لا حِزم جداول إحداثيات بعد. كل عملية بناء تكتب',
  'No bookmarked tables. Star a table below after switching the filter off.':
    'لا جداول مفضّلة. ضع نجمة على جدول أدناه بعد إيقاف المرشِّح.',
  'No ground control points yet. Mark a landmark in the photo, then click the matching spot on the map to place one.':
    'لا نقاط ضبط أرضية بعد. حدِّد معلَمًا في الصورة، ثم انقر الموضع المطابق على الخريطة لوضع نقطة.',
  'No landmarks to work with': 'لا معالم للعمل عليها',
  'No lookup table chosen — objects are detected and counted but not placed on the map.':
    'لم يُختَر جدول إحداثيات — تُكتشَف الأجسام وتُعدّ لكنها لا تُوضَع على الخريطة.',
  'No matches. Try a different spelling, or type coordinates below.':
    'لا نتائج. جرّب هجاءً مختلفًا، أو اكتب إحداثيات أدناه.',
  'No project selected — a DEM processed here would feed':
    'لم يُختَر مشروع — نموذج الارتفاع المعالَج هنا سيغذّي',
  'No saved versions yet. Edits are autosaved and will appear here.':
    'لا نسخ محفوظة بعد. تُحفَظ التعديلات تلقائيًا وستظهر هنا.',
  'Not enabled in this build': 'غير مُفعّل في هذه النسخة',
  'Not enough anchor points': 'نقاط الارتكاز غير كافية',
  'Nothing here yet — process a DEM and its output appears in this library automatically.':
    'لا شيء هنا بعد — عالِج نموذج ارتفاع وسيظهر ناتجه في هذه المكتبة تلقائيًا.',
  'Nothing re-measures until you press the button below.': 'لا يُعاد القياس حتى تضغط الزر أدناه.',
  'Oldest first': 'الأقدم أولًا',
  'Outside imagery coverage': 'خارج تغطية الصور',
  'PDF report': 'تقرير PDF',
  'Pair photo pixels with map positions. After four, auto GCP picking can estimate new points from a single click.':
    'اربط بكسلات الصورة بمواضع الخريطة. بعد أربع نقاط، يستطيع الانتقاء التلقائي تقدير نقاط جديدة بنقرة واحدة.',
  'Pick the project this video belongs to — frames you capture from it become that project’s photographs.':
    'اختر المشروع الذي ينتمي إليه هذا الفيديو — تصبح الإطارات التي تلتقطها منه صورًا لذلك المشروع.',
  'Pre-cached offline tiles': 'بلاطات مخزّنة مسبقًا دون اتصال',
  'Process new DEM…': 'معالجة نموذج ارتفاع جديد…',
  'Provider did not respond': 'لم يستجب المزوّد',
  'Provider is rate-limited': 'المزوّد مُقيَّد بمعدّل الطلبات',
  'Provider unavailable': 'المزوّد غير متاح',
  'Recommended — picks the correct zone from the data':
    'مُوصى به — يختار المنطقة الصحيحة من البيانات',
  'Recorded as a': 'مُسجَّلة كـ',
  'Refining positions? Import KML/KMZ…': 'تحسين المواضع؟ استورد KML/KMZ…',
  'Reload editor': 'إعادة تحميل المحرر',
  'Road intersection': 'تقاطع طرق',
  'Seek to a second, then capture that frame to annotate it as a photo.':
    'انتقل إلى ثانية معيّنة، ثم التقط ذلك الإطار لتوصيفه كصورة.',
  'Select an image to place ground control points on the map.':
    'اختر صورة لوضع نقاط الضبط الأرضية على الخريطة.',
  'Select the': 'اختر',
  'Service temporarily unavailable': 'الخدمة غير متاحة مؤقتًا',
  'Starting export…': 'جارٍ بدء التصدير…',
  'Take the coordinates to your GIS or CAD — with the CE90 accuracy that tells you how far to trust each one.':
    'انقل الإحداثيات إلى نظام المعلومات الجغرافية أو برنامج التصميم لديك — مع دقة CE90 التي تخبرك بمدى الثقة بكل نقطة.',
  'The lookup table must have been built for': 'يجب أن يكون جدول الإحداثيات قد بُني من أجل',
  'The panels below still show the last applied settings. Press':
    'لا تزال اللوحات أدناه تعرض آخر إعدادات مطبَّقة. اضغط',
  'The refined pose only — the local residual field is never extrapolated, so it is not baked into a full-frame table.':
    'الوضع المُحسَّن فقط — لا يُستقرَأ حقل البواقي المحلي أبدًا، لذا لا يُدمَج في جدول كامل الإطار.',
  'The stride is wider than the tile, so the tiles would not overlap and most of the scene would go unmeasured.':
    'الخطوة أوسع من البلاطة، لذا لن تتداخل البلاطات وسيبقى معظم المشهد دون قياس.',
  'The tracker locks the moment': 'يثبّت المتعقّب في اللحظة التي',
  'There are no ground control points to export yet. Place GCPs manually first.':
    'لا توجد نقاط ضبط أرضية للتصدير بعد. ضع نقاط الضبط يدويًا أولًا.',
  'These dimensions could not be read in the browser, so this photo will upload at its native resolution.':
    'تعذّرت قراءة هذه الأبعاد في المتصفح، لذا ستُرفَع هذه الصورة بدقتها الأصلية.',
  'This format can’t play in the browser. Seeking and capturing still work: frames are rendered on the server.':
    'لا يمكن تشغيل هذه الصيغة في المتصفح. لكن التمرير والالتقاط يعملان: تُولَّد الإطارات على الخادم.',
  'This is a direct observation — there is no match to re-fit. To move it, re-open the pairing and drag either endpoint.':
    'هذه ملاحظة مباشرة — لا يوجد تطابق لإعادة ملاءمته. لتحريكها، أعِد فتح الاقتران واسحب أيًّا من طرفيه.',
  'This source is blocked by the server’s provider list': 'هذا المصدر محظور بقائمة مزوّدي الخادم',
  'This source is not configured on the server': 'هذا المصدر غير مُهيَّأ على الخادم',
  'Timed out': 'انتهت المهلة',
  'Unsupported format': 'صيغة غير مدعومة',
  'Upload DEM for this image…': 'رفع نموذج ارتفاع لهذه الصورة…',
  'Using the': 'باستخدام',
  'Water body': 'مسطّح مائي',
  'Where should we search?': 'أين نبحث؟',
  'Where the camera stood for this photograph (WGS84 decimal degrees) and its height above the ground. Tilt is degrees':
    'موضع الكاميرا عند التقاط هذه الصورة (درجات عشرية WGS84) وارتفاعها عن الأرض. والميل بالدرجات',
  'Where the next control point would remove the most predicted error.':
    'حيث تزيل نقطة الضبط التالية أكبر قدر من الخطأ المتوقّع.',
  'You can still capture the frame — the server renders it on capture.':
    'لا يزال بإمكانك التقاط الإطار — يقوم الخادم بتوليده عند الالتقاط.',
  'Your preprocessed elevation model becomes the project’s only height source — honest Z, never a guess.':
    'يصبح نموذج الارتفاع المعالَج مسبقًا مصدر الارتفاع الوحيد للمشروع — قيمة Z صادقة، لا تخمين.',
  'Z — no DEM': 'Z — لا نموذج ارتفاع',
  'Z — no data': 'Z — لا بيانات',
  'all work.': 'كلها تعمل.',
  'altitude ignored': 'تم تجاهل الارتفاع',
  'and becomes an ordinary photograph in any project.': 'ويصبح صورة عادية في أي مشروع.',
  'and the API is restarted — pointing the map at an unconfigured provider would only render a grid of failed tiles.':
    'ويُعاد تشغيل الواجهة البرمجية — فتوجيه الخريطة إلى مزوّد غير مُهيَّأ لن يعرض سوى شبكة من البلاطات الفاشلة.',
  'becomes a photograph in the project. Leave the extension off — “.jpg” is added for you.':
    'يصبح صورة في المشروع. اترك الامتداد — تُضاف «.jpg» نيابة عنك.',
  'below horizontal': 'تحت الأفقي',
  'capture library': 'مكتبة اللقطات',
  'default provider. Set its credentials in backend/.env and restart the API (details in the workspace settings dialog).':
    'المزوّد الافتراضي. اضبط بيانات اعتماده في backend/.env وأعِد تشغيل الواجهة البرمجية (التفاصيل في نافذة إعدادات مساحة العمل).',
  'derived from the camera position — the DEM is reprojected into this zone':
    'مُشتقّة من موضع الكاميرا — يُعاد إسقاط نموذج الارتفاع في هذه المنطقة',
  'folder, and it appears here — permanently, across restarts.':
    'مجلدًا، ويظهر هنا — بشكل دائم، عبر عمليات إعادة التشغيل.',
  'in the source tree. Editing the wrong one changes nothing.':
    'في شجرة المصدر. تعديل الملف الخطأ لا يغيّر شيئًا.',
  'key,value': 'key,value',
  'local capture device': 'جهاز التقاط محلي',
  'no elevation': 'لا ارتفاع',
  'no project': 'لا مشروع',
  'no valid elevation cells': 'لا خلايا ارتفاع صالحة',
  'no vertical accuracy figure': 'لا رقم للدقة الرأسية',
  'not in ground metres — reprojection was skipped':
    'ليست بالأمتار الأرضية — تم تخطّي إعادة الإسقاط',
  'or coordinates': 'أو إحداثيات',
  'project DEM': 'نموذج ارتفاع المشروع',
  'running copy’s': 'النسخة قيد التشغيل',
  'the error there.': 'الخطأ هناك.',
  'the winning stage': 'المرحلة الفائزة',
  'the worst areas — read this one': 'أسوأ المناطق — اقرأ هذا',
  'to commit without reaching for the button.': 'للتثبيت دون الحاجة إلى الزر.',
  'to see these — or': 'لرؤية هذه — أو',
  'tool and click a landmark in the photo, then link it to the satellite map to record a ground control point.':
    'ثم انقر على معلَم في الصورة واربطه بخريطة الأقمار الصناعية لتسجيل نقطة ضبط أرضية.',
  'will be permanently removed. This cannot be undone. If it was placed from a landmark, that landmark stays in the photo.':
    'ستُحذف نهائيًا. لا يمكن التراجع عن ذلك. وإن كانت قد وُضعت من معلَم، يبقى ذلك المعلَم في الصورة.',
  '— it answers for one frozen pose, and marks are only as right as that match.':
    '— فهو يجيب عن وضع واحد مجمَّد، والعلامات صحيحة بقدر صحة ذلك التطابق.',
  '★ In the installed app that setting is read from the':
    '★ في التطبيق المثبّت تُقرأ هذه الإعدادات من',

  // ── the long guidance: what each choice costs and why ─────────────────────
  '10 m pixels, and the provider refuses zoom beyond 15 rather than faking detail: right for locating an area and monitoring change, WRONG for precise GCP clicking — a gate post is smaller than one pixel. Needs LE_COPERNICUS_CLIENT_ID / _CLIENT_SECRET / _INSTANCE_ID in backend/.env (free account at dataspace.copernicus.eu), then an API restart.':
    'بكسلات بحجم ١٠ أمتار، والمزوّد يرفض التكبير بعد المستوى ١٥ بدل تزييف التفاصيل: مناسب لتحديد منطقة ومتابعة التغيّر، وغير مناسب للنقر الدقيق على نقاط الضبط — فعمود بوابة أصغر من بكسل واحد. يتطلب LE_COPERNICUS_CLIENT_ID / _CLIENT_SECRET / _INSTANCE_ID في backend/.env (حساب مجاني على dataspace.copernicus.eu)، ثم إعادة تشغيل الواجهة البرمجية.',
  '3D needs an elevation source. This project has no DEM attached, so terrain would render dead flat — which would look like real ground and be wrong. Attach a DEM in the workspace setup to enable it.':
    'يحتاج العرض ثلاثي الأبعاد إلى مصدر ارتفاع. لا يوجد نموذج ارتفاع مرفق بهذا المشروع، لذا ستظهر التضاريس مسطّحة تمامًا — وهو ما سيبدو أرضًا حقيقية لكنه خاطئ. أرفِق نموذج ارتفاع في إعداد مساحة العمل لتفعيله.',
  'A placemark carries a ground coordinate but no image pixel, and a GCP is a pairing of the two — so new placemarks are reported, never created. Pair those in the workspace against the photo they belong to.':
    'تحمل العلامة المكانية إحداثيًا أرضيًا لكن دون بكسل في الصورة، ونقطة الضبط هي اقتران الاثنين — لذا يُبلَّغ عن العلامات الجديدة ولا تُنشأ أبدًا. اقرِنها في مساحة العمل بالصورة التي تنتمي إليها.',
  'Always applied. Distances, slopes and ray geometry are only meaningful in metres — a degree of longitude is 111 km at the equator and 64 km at 55°N. Skipped automatically if the DEM is already in a metre grid.':
    'يُطبَّق دائمًا. المسافات والميول وهندسة الأشعة لا معنى لها إلا بالأمتار — فدرجة خط الطول تساوي ١١١ كم عند خط الاستواء و٦٤ كم عند ٥٥° شمالًا. ويُتخطّى تلقائيًا إن كان نموذج الارتفاع بشبكة مترية أصلًا.',
  'Builds a frozen pixel→latitude/longitude table for one photograph of a fixed camera: the pose is solved from its committed GCPs, every pixel is ray-cast against the project’s DEM, and the result is packaged for a field unit that answers with a single array read.':
    'يبني جدولًا مجمَّدًا من البكسل إلى خط العرض/الطول لصورة واحدة من كاميرا ثابتة: يُحَل الوضع من نقاط الضبط المثبَّتة، ويُسقَط شعاع لكل بكسل على نموذج ارتفاع المشروع، ثم تُحزَم النتيجة لوحدة ميدانية تجيب بقراءة مصفوفة واحدة.',
  'Caches the area you are working in (current zoom, plus a small buffer) into the same offline cache the manual area download uses.':
    'يخزّن المنطقة التي تعمل فيها (التكبير الحالي مع هامش صغير) في التخزين المؤقت نفسه الذي يستخدمه تنزيل المنطقة يدويًا.',
  'Decimal degrees or DMS —': 'درجات عشرية أو DMS —',
  'Every figure is measured against the satellite basemap, which carries its own georeferencing error of a few metres. Breaking that floor needs GNSS-surveyed checkpoints.':
    'كل رقم يُقاس مقابل خريطة الأقمار الصناعية الأساسية، التي تحمل خطأ إسناد جغرافي خاصًا بها يبلغ بضعة أمتار. وتجاوز هذا الحد يتطلب نقاط تحقّق مساحة بنظام GNSS.',
  'Keyless — always available, no account or token. Satellite, hybrid and terrain views. ±8 m georeferencing (an estimate: the mosaic mixes many vendors, so alignment varies by region).':
    'بلا مفتاح — متاح دائمًا، دون حساب أو رمز. عروض الأقمار الصناعية والهجين والتضاريس. إسناد جغرافي ±٨ أمتار (تقدير: الفسيفساء تمزج عدة مزوّدين، لذا تتفاوت المحاذاة حسب المنطقة).',
  'Name it, upload the first photograph, and enter its camera setup — the calibration CSV from the field tool imports in one click.':
    'سمِّه، وارفع الصورة الأولى، وأدخِل إعداد كاميرتها — ويُستورَد ملف المعايرة CSV من الأداة الميدانية بنقرة واحدة.',
  'Name this survey, describe it, and choose the elevation model (DEM) every image in it reads heights from. You can change any of this later from the project page.':
    'سمِّ هذا المسح وصِفه واختر نموذج الارتفاع (DEM) الذي تقرأ منه كل صورة فيه ارتفاعاتها. ويمكنك تغيير أي من ذلك لاحقًا من صفحة المشروع.',
  'Needs LE_MAPBOX_ACCESS_TOKEN in backend/.env (a public token from a free account at mapbox.com — the free tier covers 200k tiles/month), then an API restart.':
    'يتطلب LE_MAPBOX_ACCESS_TOKEN في backend/.env (رمز عام من حساب مجاني على mapbox.com — الباقة المجانية تغطي ٢٠٠ ألف بلاطة شهريًا)، ثم إعادة تشغيل الواجهة البرمجية.',
  'No detector connected — YOLO object detection is planned. Detected classes will appear here, one labeled counter per class.':
    'لا كاشف متصل — كشف الأجسام بـ YOLO مخطَّط له. ستظهر الأصناف المكتشفة هنا، بعدّاد موسوم لكل صنف.',
  'Nothing here yet. Capture frames from a video and they appear in this library automatically, ready to reuse in any project.':
    'لا شيء هنا بعد. التقط إطارات من فيديو وستظهر في هذه المكتبة تلقائيًا، جاهزة لإعادة الاستخدام في أي مشروع.',
  'Takes effect at the next measurement — the ranking is scored against the error field, so it is recomputed rather than trimmed.':
    'يسري مفعوله عند القياس التالي — إذ يُحتسَب الترتيب مقابل حقل الخطأ، فيُعاد حسابه بدل اقتطاعه.',
  'The photograph these settings describe. Uploading it fills the blank frame-size and image-centre fields below from its dimensions.':
    'الصورة التي تصفها هذه الإعدادات. ورفعها يملأ حقول حجم الإطار ومركز الصورة الفارغة أدناه من أبعادها.',
  'The typical error improved but the worst areas got worse. Most of the scene is better and a minority is worse — check the right-hand map before treating this as a straight gain.':
    'تحسّن الخطأ النموذجي لكن أسوأ المناطق ازدادت سوءًا. معظم المشهد أفضل وأقلية أسوأ — راجع الخريطة اليمنى قبل اعتبار هذا مكسبًا صافيًا.',
  'This is the first measurement, so there is nothing before it to compare against — the numbers below describe it on its own.':
    'هذا هو القياس الأول، فلا شيء قبله للمقارنة به — والأرقام أدناه تصفه بمفرده.',
  'This server does not serve the cross-project GCP overview yet, so the tables cannot be listed here. Each project’s tables remain available in its editor.':
    'لا يوفّر هذا الخادم بعد نظرة عامة على نقاط الضبط عبر المشاريع، لذا لا يمكن سرد الجداول هنا. تبقى جداول كل مشروع متاحة داخل محرره.',
  'Tilted terrain from this project’s DEM, with the same imagery draped over it. Viewing aid only: GCP markers and overlays stay in the 2D pane, and the rendered surface is approximate — a point’s elevation always comes from the DEM sampler.':
    'تضاريس مائلة من نموذج ارتفاع هذا المشروع، مع الصور نفسها منسدلة فوقها. أداة عرض فقط: تبقى علامات نقاط الضبط والطبقات في اللوحة ثنائية الأبعاد، والسطح المعروض تقريبي — فارتفاع أي نقطة يأتي دائمًا من قارئ نموذج الارتفاع.',
  'What you click on to place a coordinate. The provider’s own georeferencing error is usually the largest term in a GCP’s accuracy.':
    'ما تنقر عليه لوضع إحداثي. وعادةً ما يكون خطأ الإسناد الجغرافي الخاص بالمزوّد أكبر مكوّن في دقة نقطة الضبط.',
  'Where the camera stood, and how far out its frames contain usable ground. The DEM is cropped to that disc — and the position also fixes the UTM zone, so there is no zone to choose.':
    'موضع وقوف الكاميرا، ومدى امتداد الأرض القابلة للاستخدام في إطاراتها. يُقتصّ نموذج الارتفاع على ذلك القرص — والموضع يحدّد أيضًا منطقة UTM، فلا منطقة تحتاج إلى اختيارها.',
  'You can change this later from the map’s settings button. The DEM is managed in the project’s setup page (Project settings).':
    'يمكنك تغيير هذا لاحقًا من زر إعدادات الخريطة. ويُدار نموذج الارتفاع في صفحة إعداد المشروع (إعدادات المشروع).',
  'Your own preprocessed DEM — already cropped and projected. Every GCP in this project reads its height from it, and ONLY from it: there is no shared or server-wide fallback. No DEM here means every point records no elevation. A point outside the DEM’s extent records none either — never a guess.':
    'نموذج الارتفاع المعالَج مسبقًا الخاص بك — مقتصّ ومُسقَط بالفعل. كل نقطة ضبط في هذا المشروع تقرأ ارتفاعها منه، ومنه وحده: لا يوجد بديل مشترك أو على مستوى الخادم. وغياب نموذج الارتفاع هنا يعني ألّا تسجّل أي نقطة ارتفاعًا. والنقطة خارج امتداد النموذج لا تسجّل ارتفاعًا أيضًا — ولا تخمين أبدًا.',
  'or by coordinates': 'أو بالإحداثيات',
  'simply does not list it, so requesting it is refused. Add it to that line (or delete the line entirely — empty means every provider is allowed) and restart the app.':
    'لا يدرجه ببساطة، لذا يُرفض طلبه. أضِفه إلى ذلك السطر (أو احذف السطر بالكامل — فالفراغ يعني السماح بكل المزوّدين) ثم أعِد تشغيل التطبيق.',
  'will be removed from the DEM library folder on this computer. Projects and images already using it keep their own copies and are not affected — but processing it again later would start from the raw tile.':
    'ستُزال من مجلد مكتبة نماذج الارتفاع على هذا الحاسوب. أما المشاريع والصور التي تستخدمها فتحتفظ بنسخها الخاصة ولا تتأثر — لكن معالجتها مجددًا لاحقًا ستبدأ من البلاطة الخام.',

  // ── the home walkthrough and the picker's own buttons ─────────────────────
  'Auto': 'تلقائي',
  'Correspondence open': 'الاقتران مفتوح',
  'Live predict': 'تنبّؤ مباشر',
  'New GCP': 'نقطة ضبط جديدة',
  'Predicting…': 'جارٍ التنبّؤ…',

  // ── the error-measurement settings popover ────────────────────────────────
  'Free the focal length in the raw solve — solve one focal scale from the control points instead of trusting the calibration. At grazing angles focal trades off against tilt, so use it when the calibration is suspect. Changing this clears the current measurement, and nothing re-measures until you press the button below.':
    'حرِّر البعد البؤري في الحل الخام — احسب مقياسًا بؤريًا واحدًا من نقاط الضبط بدل الوثوق بالمعايرة. فعند الزوايا المائلة يتبادل البعد البؤري التأثير مع الميل، لذا استخدمه حين تكون المعايرة مشكوكًا فيها. تغيير هذا يمسح القياس الحالي، ولا يُعاد القياس حتى تضغط الزر أدناه.',
  'Max range (m)': 'أقصى مدى (م)',
  'Measure automatically after every control point — the error, the correction and the next suggestion, without asking. Off: nothing measures until you press Measure again.':
    'قِس تلقائيًا بعد كل نقطة ضبط — الخطأ والتصحيح والاقتراح التالي، دون سؤال. وعند الإيقاف: لا يُجرى أي قياس حتى تضغط «قياس مرة أخرى».',
  'Ortho GSD (m)': 'مسافة العيّنة الأرضية للصورة المقوّمة (م)',
  'Satellite zoom': 'تكبير القمر الصناعي',
  'Stride (m)': 'الخطوة (م)',
  'Tile (m)': 'البلاطة (م)',
  'Your photograph is flattened onto the terrain and matched against satellite imagery in overlapping tiles. Wherever the two match, the offset between them is the error there.':
    'تُسطَّح صورتك على التضاريس وتُطابَق مع صور الأقمار الصناعية في بلاطات متداخلة. وحيثما تطابقت الاثنتان، يكون الإزاحة بينهما هو الخطأ في ذلك الموضع.',
  'Download the processed elevation model as a GeoTIFF.':
    'نزِّل نموذج الارتفاع المعالَج بصيغة GeoTIFF.',
  'You can keep it selected, but the map will stay on the server’s default provider until the variables in the note above are set in the running copy’s .env file, and the API is restarted — pointing the map at an unconfigured provider would only render a grid of failed tiles.':
    'يمكنك إبقاؤه مختارًا، لكن الخريطة ستظل على المزوّد الافتراضي للخادم حتى تُضبَط المتغيّرات المذكورة في الملاحظة أعلاه في ملف ‎.env الخاص بالنسخة قيد التشغيل، ويُعاد تشغيل الواجهة البرمجية — فتوجيه الخريطة إلى مزوّد غير مُهيَّأ لن يعرض سوى شبكة من البلاطات الفاشلة.',
  'Copy': 'نسخ',
  'Copied': 'تم النسخ',

  // ── the shell: command palette, cheatsheet, connection chip ───────────────
  'API unreachable': 'تعذّر الوصول إلى الخادم',
  'Adjust the selected GCP': 'تعديل نقطة الضبط المحددة',
  'Change theme': 'تغيير المظهر',
  'Close dialog / cancel': 'إغلاق النافذة / إلغاء',
  'Command palette': 'لوحة الأوامر',
  'Commit the open correspondence': 'تثبيت الاقتران المفتوح',
  'Degraded': 'متدهور',
  'Delete the selected GCP': 'حذف نقطة الضبط المحددة',
  'Everywhere': 'في كل مكان',
  'Keyboard shortcuts': 'اختصارات لوحة المفاتيح',
  'Not ready': 'غير جاهز',
  'Nothing matches — try another word.': 'لا نتائج مطابقة — جرّب كلمة أخرى.',
  'Online': 'متصل',
  'Reduce animation': 'تقليل الحركة',
  'Switch language': 'تبديل اللغة',
  'System status': 'حالة النظام',
  'The API did not answer — the app cannot reach its own server.':
    'لم يستجب الخادم — لا يستطيع التطبيق الوصول إلى خادمه.',
  'Turn animations on': 'تشغيل الحركة',
  'Type a page or an action…': 'اكتب اسم صفحة أو إجراء…',
  'Undo': 'تراجع',
  'Zoom in / out': 'تكبير / تصغير',
  'COMMIT': 'تثبيت',
  'Exit focus mode': 'الخروج من وضع التركيز',
  'Focus one pane / cycle': 'تركيز لوحة واحدة / تدوير',
  'Focus the map': 'تكبير لوحة الخريطة',
  'Focus the photograph': 'تكبير لوحة الصورة',
  'Map': 'الخريطة',
  'Swap the photo and map panes': 'تبديل لوحتي الصورة والخريطة',
  'Switch panes': 'تبديل اللوحتين',
  'Delete selected': 'حذف المحدد',
  'Delete {n} ground control points?': 'حذف {n} من نقاط الضبط الأرضية؟',
  'Deleted {n} ground control points.': 'حُذفت {n} من نقاط الضبط الأرضية.',
  'Deleting…': 'جارٍ الحذف…',
  'Stopped after deleting {n} — the next delete failed.': 'توقف بعد حذف {n} — فشل الحذف التالي.',
  'They will be permanently removed. This cannot be undone. Landmarks placed from the photo stay in the photo.':
    'ستُحذف نهائيًا. لا يمكن التراجع عن ذلك. المعالم الموضوعة من الصورة تبقى في الصورة.',
  '{n} selected': 'تم تحديد {n}',

  // ── The workflow guide (/guide) — the method as a board ──────────────────
  'Workflow guide': 'دليل سير العمل',
  'Expand all': 'توسيع الكل',
  'Collapse all': 'طيّ الكل',
  'Expand step': 'توسيع الخطوة',
  'Collapse step': 'طيّ الخطوة',
  'or': 'أو',
  'Every step from an empty project to exported coordinates — in order, with a door into each. Click a step to unfold it.':
    'كل خطوة من مشروع فارغ إلى إحداثيات مُصدَّرة — بالترتيب، ولكل خطوة باب يفتح صفحتها. انقر على أي خطوة لعرض تفاصيلها.',
  'A project holds one site’s photographs, the ground control points you place in them, and their exports.':
    'المشروع يضم صور موقع واحد، ونقاط الضبط الأرضية التي تضعها فيها، وما يُصدَّر منها.',
  'Open the Workspace and press “New project”.': 'افتح مساحة العمل واضغط «مشروع جديد».',
  'Open Projects and press “New project”.': 'افتح المشاريع واضغط «مشروع جديد».',
  'Name it — you land on Project settings.': 'سمِّه — ثم تصل إلى إعدادات المشروع.',
  'Add a description and choose the project-wide elevation model. Photographs can override it later.':
    'أضف وصفًا واختر نموذج الارتفاع الرقمي للمشروع كله. يمكن لكل صورة تجاوزه لاحقًا.',
  'Prepare the elevation model (DEM)': 'تجهيز نموذج الارتفاع الرقمي (DEM)',
  'The DEM is the terrain the geolocation stands on — every ray from the camera ends where it meets this surface.':
    'نموذج الارتفاع هو الأرض التي يقف عليها تحديد المواقع — كل شعاع من الكاميرا ينتهي حيث يلتقي بهذا السطح.',
  'Drag a raw elevation file into the upload box (.tif, .hgt, .dt2, …).':
    'اسحب ملف ارتفاعات خامًا إلى صندوق الرفع (.tif, .hgt, .dt2, …).',
  'Enter where the camera stood and a radius — the DEM is cropped to that disc and reprojected into metres.':
    'أدخل موقع الكاميرا ونصف قطر — يُقتطع النموذج على ذلك القرص ويُعاد إسقاطه بالأمتار.',
  'Pick the target project, so the processed DEM feeds it.':
    'اختر المشروع الهدف، كي يغذّيه النموذج المعالَج.',
  'Process — the result lands in the library, ready to reuse.':
    'عالِج — والنتيجة تستقر في المكتبة جاهزة لإعادة الاستخدام.',
  'Open DEM processing': 'فتح معالجة نموذج الارتفاع',
  'Bring in the photograph': 'إحضار الصورة',
  'Two doors, one destination: a photograph in your project, ready for setup.':
    'بابان ووجهة واحدة: صورة داخل مشروعك جاهزة للإعداد.',
  'From an image file': 'من ملف صورة',
  'Open your project and press “Add image” — the photo uploads straight into setup.':
    'افتح مشروعك واضغط «إضافة صورة» — تُرفع الصورة مباشرة إلى الإعداد.',
  'Open your projects': 'فتح مشاريعك',
  'From a field video': 'من فيديو ميداني',
  'Upload the video, scrub to the right moment, and capture that frame.':
    'ارفع الفيديو، وتنقّل إلى اللحظة المناسبة، والتقط ذلك الإطار.',
  'Open Recorded videos': 'افتح الفيديوهات المسجّلة',
  'Describe the camera': 'وصف الكاميرا',
  'Image setup asks for everything the maths needs: the photo, the calibration, the pose.':
    'صفحة إعداد الصورة تطلب كل ما تحتاجه الحسابات: الصورة والمعايرة والوضعية.',
  'Pick the camera calibration — the intrinsics of the camera that shot it.':
    'اختر معايرة الكاميرا — الخصائص الداخلية للكاميرا التي التقطتها.',
  'Enter the camera position: latitude, longitude, height.':
    'أدخل موقع الكاميرا: خط العرض، خط الطول، الارتفاع.',
  'Enter the tilt and heading it was pointed with, then save.':
    'أدخل الميل والاتجاه اللذين وُجّهت بهما، ثم احفظ.',
  'Lives inside your project — “Add image”, or an existing photograph’s Setup button.':
    'تقع داخل مشروعك — عبر «إضافة صورة»، أو زر الإعداد لصورة موجودة.',
  'Generate the lookup table (LUT)': 'توليد جدول الإحداثيات (LUT)',
  'The LUT welds calibration, pose and DEM into one answer per pixel: which ground coordinate it sees.':
    'جدول الإحداثيات يدمج المعايرة والوضعية ونموذج الارتفاع في جواب واحد لكل بكسل: أي إحداثية أرضية يرى.',
  'Choose the photograph’s setup and the processed DEM.':
    'اختر إعداد الصورة ونموذج الارتفاع المعالَج.',
  'Build — the finished LUT lands in the library.': 'ابنِ — والجدول الجاهز يستقر في المكتبة.',
  'The editor, Auto GCP and both detectors all read from it.':
    'يقرأ منه المحرر وميزة GCP التلقائي وكلا الكاشفين.',
  'Open the LUT generator': 'فتح مولّد جدول الإحداثيات',
  'Place ground control points in the Editor': 'وضع نقاط الضبط الأرضية في المحرر',
  'The core act: pair what the camera sees with where it stands on Earth.':
    'الفعل الجوهري: مطابقة ما تراه الكاميرا مع موضعه على الأرض.',
  'Open a photograph — three panes: photo, satellite map, GCP dock.':
    'افتح صورة — ثلاث لوحات: الصورة وخريطة الأقمار الصناعية ولوحة نقاط الضبط.',
  'Click a recognisable landmark on the photograph…': 'انقر على معلم مميز في الصورة…',
  '…then the same physical spot on the satellite map.':
    '…ثم على البقعة الفعلية نفسها على خريطة الأقمار الصناعية.',
  'Press F1 to commit the pair — it becomes a ground control point.':
    'اضغط F1 لتثبيت الزوج — فيصبح نقطة ضبط أرضية.',
  'Or let Auto GCP and Live predict suggest points you confirm.':
    'أو دع GCP التلقائي والتنبؤ المباشر يقترحان نقاطًا تؤكدها أنت.',
  '⇧F focuses one pane; Esc returns to the split view.':
    '⇧F يركّز لوحة واحدة؛ وEsc يعيد العرض المقسوم.',
  'Measure the error': 'قياس الخطأ',
  'Accuracy is a measurement, not a mood — press Measure and every point earns its band.':
    'الدقة قياس لا انطباع — اضغط «قياس» فتحصل كل نقطة على نطاقها.',
  'In the editor’s accuracy panel, press “Measure” — it never runs on its own.':
    'في لوحة الدقة داخل المحرر اضغط «قياس» — فهو لا يعمل من تلقاء نفسه أبدًا.',
  'Each point gets an accuracy band, colour and shape together: high, moderate, low, unreliable.':
    'كل نقطة تحصل على نطاق دقة، باللون والشكل معًا: عالية، متوسطة، منخفضة، غير موثوقة.',
  'Inside the editor you opened in the previous step.': 'داخل المحرر الذي فتحته في الخطوة السابقة.',
  'Detect and geolocate automatically': 'الكشف وتحديد المواقع تلقائيًا',
  'Optional: let the detector place the points — with a lookup table chosen, every find lands on the map.':
    'اختياري: دع الكاشف يضع النقاط — ومع اختيار جدول الإحداثيات، يحطّ كل اكتشاف على الخريطة.',
  'Pick a clip, a model and class, and a tracker — detections are drawn live and plotted on the map.':
    'اختر مقطعًا ونموذجًا وفئة ومتعقّبًا — تُرسم الاكتشافات مباشرة وتُوقَّع على الخريطة.',
  'The same choices on a connected camera, in real time.':
    'الخيارات نفسها على كاميرا متصلة، في الوقت الفعلي.',
  'Open the Live stream': 'فتح البث المباشر',
  'Export your work': 'تصدير عملك',
  'The coordinates leave with you: CSV, GeoJSON or Shapefile.':
    'الإحداثيات ترحل معك: CSV أو GeoJSON أو Shapefile.',
  'Open GCP tables — every photograph’s committed points, in one place.':
    'افتح جداول نقاط الضبط — النقاط المثبتة لكل صورة في مكان واحد.',
  'Export as CSV, GeoJSON or Shapefile.': 'صدّر بصيغة CSV أو GeoJSON أو Shapefile.',
  'The detection pages export their own attribute table the same way — date, time, camera name and camera location included.':
    'صفحات الكشف تصدّر جدول خصائصها بالطريقة نفسها — متضمنًا التاريخ والوقت واسم الكاميرا وموقعها.',
  'Open GCP tables': 'فتح جداول نقاط الضبط',

  // ── The camera drift watch (freeze / check / monitor) ────────────────────
  'Drift watch': 'مراقبة الانحراف',
  'Camera steady': 'الكاميرا ثابتة',
  'Camera moved': 'الكاميرا تحركت',
  'Optics changed': 'العدسة تغيّرت',
  'Cannot judge': 'لا يمكن الحكم',
  'Camera moved — coordinates are no longer trusted.': 'الكاميرا تحركت — الإحداثيات لم تعد موثوقة.',
  'Camera optics changed — coordinates are no longer trusted.':
    'عدسة الكاميرا تغيّرت — الإحداثيات لم تعد موثوقة.',
  'Re-aim the camera or re-solve the pose, then freeze a new reference.':
    'أعد توجيه الكاميرا أو أعد حل الوضعية، ثم جمّد مرجعًا جديدًا.',
  'The mapping needs a full re-solve — re-aiming will not fix it.':
    'الربط يحتاج إعادة حل كاملة — إعادة التوجيه لن تصلحه.',
  'since': 'منذ',
  'Choose and apply a source above first.': 'اختر مصدرًا في الأعلى وطبّقه أولًا.',
  'Apply a lookup table above — the reference needs it to give each landmark its ground position.':
    'طبّق جدول إحداثيات في الأعلى — المرجع يحتاجه ليعطي كل معلم موضعه الأرضي.',
  'Reference frozen — no check has run yet.': 'المرجع مجمّد — لم يُجرَ أي فحص بعد.',
  'No reference for this view yet. Freeze one while the aim is trusted.':
    'لا مرجع لهذا المشهد بعد. جمّده بينما التوجيه موثوق.',
  'Check now': 'افحص الآن',
  'Check interval': 'فاصل الفحص',
  'Watch': 'راقب',
  'Stop watching': 'إيقاف المراقبة',
  'Freeze reference': 'تجميد المرجع',
  'Re-freeze': 'إعادة التجميد',
  'Watch stopped:': 'توقفت المراقبة:',
  'Last look failed:': 'فشلت آخر نظرة:',
  '{n} landmarks': '{n} معالم',
  'alert above': 'تنبيه فوق',
  'frozen': 'جُمِّد',
  'at second': 'عند الثانية',
  'check at second': 'افحص عند الثانية',
  'alert above (m)': 'تنبيه فوق (م)',
  'frozen at': 'جُمِّد عند',
  'That is the frozen second — checking it against itself proves nothing. Pick another second.':
    'هذه هي الثانية المجمّدة — فحصها مقابل نفسها لا يثبت شيئًا. اختر ثانية أخرى.',
  'Clip checks confirm immediately — each one is a deliberate look.':
    'فحوص المقاطع تُؤكَّد فورًا — كل فحص نظرة متعمدة.',
  'confirmed:': 'المؤكَّد:',
  'this frame': 'هذا الإطار',
  // ── the navbar's two workspaces, and the workchain ────────────────────────
  'Locator Workspace': 'مساحة التحديد',
  'Locator': 'التحديد',
  'Monitoring': 'المراقبة',
  'Monitoring Workspace': 'مساحة المراقبة',
  'Build the geolocation — projects, terrain, lookup tables and control points.':
    'ابنِ التحديد الجغرافي — المشاريع والتضاريس وجداول الإحداثيات ونقاط الضبط.',
  'Watch cameras and clips, detect what moves, and know when the camera itself has.':
    'راقب الكاميرات والمقاطع، واكشف ما يتحرك، واعرف متى تحركت الكاميرا نفسها.',
  'Every survey site: its photographs, their setups and the points placed in them.':
    'كل موقع مسح: صوره وإعداداتها والنقاط الموضوعة فيها.',
  'Crop and reproject an elevation model — the terrain every ray lands on.':
    'قصّ نموذج الارتفاع وأعد إسقاطه — التضاريس التي يستقر عليها كل شعاع.',
  'Solve a whole photograph in advance: one ground coordinate per pixel.':
    'حلّ الصورة كاملة مسبقًا: إحداثية أرضية لكل بكسل.',
  'Every committed control point, by photograph, with its accuracy — and the exports.':
    'كل نقطة ضبط مثبّتة، حسب الصورة، مع دقتها — والتصديرات.',
  'A connected camera, in real time — measure, detect and capture from it.':
    'كاميرا متصلة في الوقت الحقيقي — قِس واكشف والتقط منها.',
  'Freeze a trusted view and be told the moment the camera moves or its optics change.':
    'ثبّت مشهدًا موثوقًا لتُعلَم لحظة تحرك الكاميرا أو تغيّر عدساتها.',
  'Drift monitor': 'مراقب الانحراف',
  'Editor': 'المحرر',
  'pages': 'صفحات',
  'open': 'مفتوحة',
  'Open': 'افتح',
  'Here': 'أنت هنا',
  'Close all': 'إغلاق الكل',

  // ── the drift monitor page ────────────────────────────────────────────────
  'A fixed camera is only as trustworthy as its aim. Freeze a reference while the view is trusted, and every later check says whether the camera has moved, whether its optics have changed, or whether the frame is too poor to judge. The monitor measures change from the reference — never whether the reference itself was right.':
    'الكاميرا الثابتة موثوقة بقدر ثبات توجيهها. ثبّت مرجعًا بينما المشهد موثوق، وسيخبرك كل فحص لاحق إن كانت الكاميرا قد تحركت، أو تغيّرت عدساتها، أو كان الإطار أضعف من أن يُحكم عليه. يقيس المراقب التغيّر عن المرجع — لا صحة المرجع نفسه أبدًا.',
  'Camera under watch': 'الكاميرا قيد المراقبة',
  'Choose a camera or a clip': 'اختر كاميرا أو مقطعًا',
  'Saved cameras': 'الكاميرات المحفوظة',
  'Library clips': 'مقاطع المكتبة',
  'Other': 'أخرى',
  'A camera URL or capture device…': 'عنوان كاميرا أو جهاز التقاط…',
  'Camera URL or device': 'عنوان الكاميرا أو الجهاز',
  'Choose the lookup table this camera was trusted with':
    'اختر جدول الإحداثيات الذي وُثقت به هذه الكاميرا',
  'validation failed': 'فشل التحقق',
  'No lookup table built yet — the reference needs one to give each landmark its ground position. Build one in the LUT generator first, or import one built elsewhere.':
    'لم يُبنَ جدول إحداثيات بعد — يحتاجه المرجع ليعطي كل معلَم موضعه الأرضي. ابنِ واحدًا في مولّد جدول الإحداثيات أولًا، أو استورد واحدًا بُني في مكان آخر.',
  'watch running': 'مراقبة جارية',
  'watches running': 'مراقبات جارية',
  'Rotation': 'الدوران',
  'Ground error': 'الخطأ الأرضي',
  'lost': 'مفقودة',
  'Inliers': 'المطابقات الصالحة',
  'Residual': 'البقايا',
  'Checked': 'وقت الفحص',
  'Recent verdicts': 'الأحكام الأخيرة',
  'Frozen references': 'المراجع المثبّتة',
  'Could not load the drift references.': 'تعذّر تحميل مراجع الانحراف.',
  'No reference frozen yet. Choose a source and its lookup table above, apply them, and freeze while the aim is trusted.':
    'لا مرجع مثبّتًا بعد. اختر مصدرًا وجدول إحداثياته أعلاه، طبّقهما، وثبّت بينما التوجيه موثوق.',
  'Reference': 'المرجع',
  'Alert above': 'تنبيه فوق',
  'Frozen': 'وقت التثبيت',
  'on demand': 'عند الطلب',
  'not watching': 'غير مراقَبة',
  'every': 'كل',
  'checks': 'فحوصات',
  'watch failed': 'فشلت المراقبة',
  'stopped': 'متوقفة',
  'looks failed (device busy)': 'محاولات فشلت (الجهاز مشغول)',
  'In use': 'قيد الاستخدام',
  'Use': 'استخدم',
  'Forget this reference': 'نسيان هذا المرجع',
  'Forget': 'نسيان',
  'Forgetting…': 'جارٍ النسيان…',
  'Forget this reference?': 'نسيان هذا المرجع؟',
  'Its watch stops and its history goes with it. The camera itself is not touched.':
    'تتوقف مراقبته ويذهب سجله معه. الكاميرا نفسها لا تُمسّ.',
  // ── the workflow guide as a course ────────────────────────────────────────
  // ★ 2026-09-12 — the guide gained a second view: every page and what it is
  //   responsible for, wired to the route both ways. The vocabulary of that view
  //   is translated here; the steps' long prose still falls back to English, as
  //   it did before, until it is translated as one pass.
  'The method in order, and every page in the app explained. The two are wired together: a step names the pages it runs on, and a page names the steps that run on it.':
    'الطريقة بالترتيب، وكل صفحة في التطبيق مشروحة. الاثنان مترابطان: الخطوة تسمّي الصفحات التي تجري عليها، والصفحة تسمّي الخطوات التي تجري فيها.',
  'View': 'العرض',
  'Route': 'المسار',
  'WHERE IT HAPPENS': 'أين تجري',
  'WHAT LIVES HERE': 'ما الذي يسكن هنا',
  'How to get here': 'كيف تصل إلى هنا',
  'no address of its own': 'لا عنوان خاص بها',
  'Not part of the route — read it when you need it.': 'ليست جزءاً من المسار — اقرأها حين تحتاجها.',
  'Search the pages': 'ابحث في الصفحات',
  'No page matches.': 'لا صفحة مطابقة.',
  'What is': 'ما هي',
  'for?': '؟ وما مسؤوليتها',
  'Every page the app has, and what each one is responsible for. The step numbers on a card take you back to that point in the route.':
    'كل صفحة في التطبيق، وما هي مسؤولة عنه. أرقام الخطوات على البطاقة تعيدك إلى تلك النقطة من المسار.',
  // the groups
  'In the navbar': 'في شريط التنقّل',
  'Inside a camera': 'داخل الكاميرا',
  'Tools': 'الأدوات',
  'Records': 'السجلات',
  'Elsewhere': 'في مواضع أخرى',
  // the pages that have no entry in the app's own registry
  'A camera’s settings': 'إعدادات الكاميرا',
  'The control-point editor': 'محرّر نقاط الضبط',
  'A camera’s monitoring page': 'صفحة مراقبة الكاميرا',
  'A recording': 'تسجيل',
  'A clip': 'مقطع',
  'App status & logs': 'حالة التطبيق والسجلات',
  // what each page is RESPONSIBLE for — the heart of the Pages view
  'The registry: which cameras exist at all. Every other page reads this list.':
    'السجل: ما الكاميرات الموجودة أصلاً. كل صفحة أخرى تقرأ هذه القائمة.',
  'Watching the fleet: where every registered camera is, and which are live right now.':
    'مراقبة الأسطول: أين تقع كل كاميرا مسجّلة، وأيّها بثّها حيّ الآن.',
  'Keeping what the cameras recorded, and the clips you uploaded by hand.':
    'حفظ ما سجّلته الكاميرات، والمقاطع التي رفعتها يدوياً.',
  'The whole setup pipeline for one camera — the eight steps that make it measurable.':
    'مسار التهيئة الكامل لكاميرا واحدة — الخطوات الثماني التي تجعلها قابلة للقياس.',
  'Pairing pixels in the frame with positions on the satellite map.':
    'مزاوجة بكسلات الإطار بمواضع على خريطة الأقمار الصناعية.',
  'One camera, watched: its picture, its detections, and where each one landed.':
    'كاميرا واحدة تحت المراقبة: صورتها، وكشوفاتها، وأين حطّ كل كشف منها.',
  'Turning a raw elevation raster into the terrain a camera can measure against.':
    'تحويل مرئية ارتفاعات خام إلى تضاريس تستطيع الكاميرا القياس عليها.',
  'Knowing the moment a camera stops pointing where it was solved for.':
    'معرفة اللحظة التي تتوقّف فيها الكاميرا عن التصويب حيث حُلّت من أجله.',
  'One recorded session, watched beside the attribute table it produced.':
    'جلسة مسجّلة واحدة، تُشاهَد إلى جانب جدول السمات الذي أنتجته.',
  'Scrubbing an uploaded video to one moment and keeping that frame as a photograph.':
    'تمرير فيديو مرفوع إلى لحظة واحدة والاحتفاظ بذلك الإطار كصورة.',
  'The state of the whole system at a glance — what is running and what needs attention.':
    'حالة المنظومة كلها بنظرة واحدة — ما الذي يعمل وما الذي يحتاج انتباهاً.',
  'This page: the method in order, and every page in the app explained.':
    'هذه الصفحة: الطريقة بالترتيب، وكل صفحة في التطبيق مشروحة.',
  'Saying which part of the system is unhappy, and showing the log that proves it.':
    'بيان أيّ جزء من المنظومة غير سليم، وعرض السجل الذي يثبت ذلك.',
  // the two new step titles
  'Record the scene': 'سجّل المشهد',
  'Export and hand over': 'صدّر وسلّم',
  'Every step from an empty project to exported coordinates — in order, with a door into each. Pick a step on the left; tick it off as you go.':
    'كل خطوة من مشروع فارغ إلى إحداثيات مصدَّرة — بالترتيب، ولكل خطوة بابها. اختر خطوة من اليسار وعلّم عليها حين تنجزها.',
  'Your progress': 'تقدّمك',
  'done': 'منجزة',
  'Reset progress': 'إعادة ضبط التقدّم',
  'Steps': 'الخطوات',
  'Set up': 'التهيئة',
  'Model the camera': 'نمذجة الكاميرا',
  'Survey': 'المسح',
  'Automate': 'الأتمتة',
  'Deliver': 'التسليم',
  'Two doors': 'بابان',
  'Opens a page': 'تفتح صفحة',
  'Inside another page': 'داخل صفحة أخرى',
  'optional': 'اختيارية',
  'Optional': 'اختيارية',
  'STEP': 'الخطوة',
  'HOW': 'كيف',
  'TWO WAYS IN': 'طريقان للدخول',
  'OPTION': 'الخيار',
  'Where it lives': 'أين تقع',
  'Mark as done': 'تعليم كمنجزة',
  'Previous': 'السابقة',
  'Next step': 'الخطوة التالية',

  // ── the LUT generator bench ───────────────────────────────────────────────
  'choose a project first': 'اختر مشروعًا أولًا',
  'photograph': 'صورة',
  'photographs': 'صور',
  'The project’s photographs will be listed here.': 'ستُعرض صور المشروع هنا.',
  'This project has no photographs yet — add one from its page first.':
    'لا صور في هذا المشروع بعد — أضف واحدة من صفحته أولًا.',
  'Enough control points to solve the pose': 'نقاط ضبط كافية لحلّ وضعية الكاميرا',
  'Needs at least {n} control points': 'يحتاج {n} نقاط ضبط على الأقل',
  'Name and build': 'التسمية والبناء',
  'Output folder': 'مجلد الإخراج',
  'payload': 'الحمولة',
  'pixels': 'بكسل',
  'Building…': 'جارٍ البناء…',
  'Ready to build?': 'جاهز للبناء؟',
  'A photograph is chosen': 'اختيرت صورة',
  'At least {n} ground control points': '{n} نقاط ضبط أرضية على الأقل',
  'committed': 'مثبّتة',
  'counted once a photograph is chosen': 'تُعدّ بعد اختيار صورة',
  'Camera set up — intrinsics and position': 'الكاميرا مُعدّة — المعاملات الداخلية والموضع',
  'verified by the server when the build starts': 'يتحقق منه الخادم عند بدء البناء',
  'Project DEM present': 'نموذج ارتفاع المشروع موجود',
  'Queued': 'في الانتظار',
  'Ray-casting every pixel': 'إسقاط الأشعة لكل بكسل',
  'Validating and packaging': 'التحقق والتعبئة',
  'queued': 'في الانتظار',
  'building': 'قيد البناء',
  'validated': 'متحقَّق منها',
  'not validated': 'غير متحقَّق منها',
  'Validation samples': 'عيّنات التحقق',
  'Max error': 'أقصى خطأ',
  'Tolerance': 'التسامح',
  'bundle': 'حزمة',
  'bundles': 'حزم',
  'passed': 'ناجح',

  // ── the DEM page ──────────────────────────────────────────────────────────
  'Stages': 'المراحل',
  'Configure': 'الإعداد',
  'running': 'جارٍ',
  'now': 'الآن',
  'later': 'لاحقًا',
  'FEEDS': 'يغذّي',
  'the selected project': 'المشروع المحدد',
  'one image': 'صورة واحدة',
  'only': 'فقط',
  'every image': 'كل الصور',
  'No project — Auto GCP there would keep reporting “no DEM”':
    'لا مشروع — سيظل الالتقاط التلقائي هناك يبلّغ «لا نموذج ارتفاع»',
  'A raw elevation raster, any size — large tiles are read in place on the desktop.':
    'ملف ارتفاع خام بأي حجم — تُقرأ البلاطات الكبيرة من مكانها على سطح المكتب.',
  'file chosen': 'اختير الملف',
  'Browse': 'استعراض',
  'read in place from disk': 'يُقرأ من مكانه على القرص',
  'Configure the crop and projection': 'إعداد القصّ والإسقاط',
  'Where the terrain matters, and the metre grid it lands on.':
    'أين تهمّ التضاريس، وشبكة الأمتار التي تستقر عليها.',
  'CORNER': 'الركن',
  'margin added on every side, as a share of the area’s own span':
    'هامش يُضاف من كل جانب، كنسبة من امتداد المنطقة نفسها',
  'Reproject to metres': 'إعادة الإسقاط إلى الأمتار',
  'always on': 'مفعّل دائمًا',
  'Crop, reproject and measure — the result is saved to the library as it finishes.':
    'قصّ وأعد الإسقاط وقِس — تُحفظ النتيجة في المكتبة فور اكتمالها.',
  'Reading the file in place': 'قراءة الملف من مكانه',
  'Uploading': 'جارٍ الرفع',
  'Cropping and reprojecting on the server': 'القصّ وإعادة الإسقاط على الخادم',
  'Measuring the result': 'قياس النتيجة',
  'Export and continue': 'التصدير والمتابعة',
  'The result is already saved in the library; export only to use it elsewhere.':
    'النتيجة محفوظة في المكتبة بالفعل؛ صدّرها فقط لاستخدامها في مكان آخر.',
  'RESULT': 'النتيجة',
  'from': 'من',
  'cropped at': 'مقصوص عند',
  'tolerance': 'تسامح',
  'whole DEM': 'نموذج الارتفاع كاملًا',
  'mean': 'المتوسط',
  'valid cells': 'خلايا صالحة',
  'void': 'فارغة',
  'no voids': 'لا فراغات',
  'Output file': 'ملف الإخراج',
  // ── shell strings that were still English (audit, Next lane) ─────────────
  'Not found': 'غير موجود',
  'Back to': 'العودة إلى',
  'Saving…': 'جارٍ الحفظ…',
  'An unexpected error occurred.': 'حدث خطأ غير متوقع.',
  'click to change': 'انقر للتغيير',
  'Theme': 'المظهر',
  'Change theme.': 'غيّر المظهر.',
  'complete': 'اكتمل',
  'image': 'صورة',
  'images': 'صور',
  'Fetching imagery': 'جلب الصور الفضائية',
  'Matching': 'المطابقة',
  'Rendering': 'التصيير',
  'Writing file': 'كتابة الملف',
  'Collecting points': 'جمع النقاط',
  'Decoding': 'فك الترميز',
  'Thumbnailing': 'إنشاء المصغّرات',
  'Image annotation canvas.': 'لوحة تعليم الصورة.',
  'landmark marked.': 'معلَم مُعلَّم.',
  'landmarks marked.': 'معالم مُعلَّمة.',
  'Use arrow keys to move the cursor, Enter to place a point, Escape to cancel.':
    'استخدم مفاتيح الأسهم لتحريك المؤشر، وEnter لوضع نقطة، وEscape للإلغاء.',
  // ── Later lane ────────────────────────────────────────────────────────────
  'Done — found in your data': 'منجزة — وُجدت في بياناتك',
  'Your project already shows this step done.': 'مشروعك يُظهر هذه الخطوة منجزة بالفعل.',
  'project': 'مشروع',
  'unsaved changes': 'تغييرات غير محفوظة',
  'Showing the first': 'عرض أول',
  'of': 'من',
  'projects.': 'مشاريع.',
  'Could not load this project’s photographs.': 'تعذّر تحميل صور هذا المشروع.',
  // ── home: the new slides and the guide section ────────────────────────────
  'Nine steps from an empty project to exported coordinates, in the order the method actually runs. Every step explains why it exists, how it is done, and opens the page where it happens — and you can tick steps off as you go.':
    'تسع خطوات من مشروع فارغ إلى إحداثيات مصدَّرة، بالترتيب الذي يجري به المنهج فعلًا. تشرح كل خطوة سبب وجودها وكيفية إنجازها وتفتح الصفحة التي تجري فيها — ويمكنك تعليم الخطوات المنجزة أثناء تقدّمك.',
  'I know my way — go to Projects': 'أعرف طريقي — إلى المشاريع',
  'Prepare the DEM': 'جهّز نموذج الارتفاع',
  'Generate the LUT': 'ولّد جدول الإحداثيات',
  'Place control points': 'ضع نقاط الضبط',
  'Detect automatically': 'اكشف تلقائيًا',
  'Reset': 'إعادة ضبط',
  // ── library-only clips (no project) ───────────────────────────────────────
  'Skip — library only': 'تخطٍّ — المكتبة فقط',
  'No project — library only': 'بلا مشروع — المكتبة فقط',
  'No project chosen — the clip goes to the video library only. You can still run detection and drift on it, and any frame you capture will ask which project it belongs to.':
    'لم يُختر مشروع — يذهب المقطع إلى مكتبة الفيديو فقط. لا يزال بإمكانك تشغيل الكشف والانحراف عليه، وأي إطار تلتقطه سيسألك عن المشروع الذي ينتمي إليه.',
  'Project for this photograph': 'مشروع هذه الصورة',
  // ── the detector lock, in the open ────────────────────────────────────────
  'The detector is locked on this machine': 'الكاشف مقفل على هذا الجهاز',
  'Could not ask the server what this machine can run.':
    'تعذّر سؤال الخادم عمّا يمكن لهذا الجهاز تشغيله.',
  'Check that the API is running, then reload this page.':
    'تأكد أن الواجهة البرمجية تعمل، ثم أعد تحميل الصفحة.',
  'Two things make it available: the runtime (`ultralytics`) in the app’s own Python, and a YOLO weights file in the models folder. Restart the API afterwards — it probes once at start.':
    'شيئان يجعلانه متاحًا: بيئة التشغيل (`ultralytics`) في بايثون التطبيق نفسه، وملف أوزان YOLO في مجلد النماذج. أعد تشغيل الواجهة البرمجية بعدها — فهي تفحص مرة واحدة عند البدء.',
  'Copy the fix': 'انسخ الحل',
  // ── importing a lookup table built elsewhere ──────────────────────────────
  //   «استيراد» is the plain surveying/computing word for bringing a prepared
  //   artefact in; the bundle itself stays «حزمة» — what is carried on the stick.
  'Import a lookup table': 'استيراد جدول إحداثيات',
  'Import a lookup table built elsewhere': 'استيراد جدول إحداثيات بُني في مكان آخر',
  'Import bundle': 'استيراد حزمة',
  'Imported from': 'مستوردة من',
  'a bundle': 'حزمة',
  'imported': 'مستوردة',
  'imported · no pose': 'مستوردة · بلا وضعية',
  'no pose in its manifest': 'لا وضعية في بيانها',
  'Add a bundle built elsewhere — on another machine, or handed over with the camera. It joins the same library the live stream, video detection and drift monitor all pick from.':
    'أضِف حزمة بُنيت في مكان آخر — على جهاز آخر، أو سُلّمت مع الكاميرا. تنضم إلى المكتبة نفسها التي يختار منها البث المباشر وكشف الفيديو ومراقب الانحراف.',
  'Drop a bundle .zip here, or choose one.': 'أفلِت حزمة ‎.zip هنا، أو اختر واحدة.',
  'Choose .zip': 'اختر ملف ‎.zip',
  'Choose folder': 'اختر مجلدًا',
  'Name in the library': 'الاسم في المكتبة',
  'Leave blank to use the bundle’s own name.': 'اتركه فارغًا لاستخدام اسم الحزمة نفسها.',
  'Filed as': 'يُحفظ باسم',
  'A bundle that carries its manifest keeps its pose and validation report. One that is only lat.npy + lon.npy can place detections, but not serve the drift monitor.':
    'الحزمة التي تحمل بيانها تحتفظ بوضعيتها وتقرير تحققها. أما التي لا تضم سوى ‎lat.npy‎ و‎lon.npy‎ فتستطيع وضع الاكتشافات على الخريطة، لكنها لا تصلح لمراقب الانحراف.',
  'Checking the bundle…': 'جارٍ فحص الحزمة…',
  'That name is taken': 'هذا الاسم مستخدَم',
  'That bundle was not imported': 'لم تُستورد هذه الحزمة',
  'Replace it': 'استبدلها',
  'A bundle built elsewhere belongs here too — use Import bundle.':
    'الحزمة المبنية في مكان آخر مكانها هنا أيضًا — استخدم «استيراد حزمة».',
  'None of the lookup tables in the library carries a camera pose, and the drift monitor re-solves geometry from it. Import a full bundle (one that includes its manifest.json), or build one here.':
    'لا يحمل أيٌّ من جداول الإحداثيات في المكتبة وضعية الكاميرا، ومراقب الانحراف يعيد حل الهندسة منها. استورد حزمة كاملة (تتضمن ملف ‎manifest.json‎)، أو ابنِ واحدة هنا.',
  'This lookup table carries no camera pose, so the drift watch cannot use it — it can still place detections. Import the full bundle (with its manifest.json), or build one in the LUT generator.':
    'جدول الإحداثيات هذا لا يحمل وضعية الكاميرا، لذا لا يستطيع مراقب الانحراف استخدامه — لكنه لا يزال يضع الاكتشافات على الخريطة. استورد الحزمة الكاملة (مع ملف ‎manifest.json‎)، أو ابنِ واحدة في مولّد جدول الإحداثيات.',
  'Play the clip — each second is judged against the frozen view as it goes.':
    'شغّل المقطع — تُحكم كل ثانية على المشهد المجمّد أثناء التشغيل.',

  // ── the monitor: the globe and a camera's page ────────────────────────────
  'Monitor': 'المراقبة',
  'Every camera on a globe — open one to watch, measure, detect and capture from it.':
    'كل كاميرا على الكرة الأرضية — افتح واحدة لمشاهدتها وقياسها والكشف والالتقاط منها.',
  'Add camera': 'إضافة كاميرا',
  'Cameras': 'الكاميرات',
  'CAMERAS': 'كاميرات',
  'LIVE': 'مباشر',
  'LOST': 'مفقود',
  'UTC time': 'التوقيت العالمي',
  'Search cameras': 'ابحث في الكاميرات',
  'No camera matches that search.': 'لا كاميرا تطابق هذا البحث.',
  'Open camera': 'فتح الكاميرا',
  'Hide camera list': 'إخفاء قائمة الكاميرات',
  'Show camera list': 'إظهار قائمة الكاميرات',
  'never opened': 'لم تُفتح بعد',
  'ago': 'مضت',
  'connecting': 'جارٍ الاتصال',
  'live': 'مباشر',
  'refused': 'مرفوض',
  'idle': 'خامل',
  'One camera': 'كاميرا واحدة',
  'Paste CSV': 'لصق CSV',
  'Import / export': 'استيراد / تصدير',
  'Heading °': 'الاتجاه °',
  'FOV °': 'زاوية الرؤية °',
  'Swap': 'تبديل',
  'Latitude and longitude look swapped. Nothing was changed — swap them if that is right.':
    'يبدو أن خطي العرض والطول متبادلان. لم يتغير شيء — بدّلهما إن كان ذلك صحيحًا.',
  'Scanning…': 'جارٍ الفحص…',
  'HDMI capture cards and USB cameras on this machine.':
    'بطاقات التقاط HDMI وكاميرات USB على هذا الجهاز.',
  'No capture devices found.': 'لم يُعثر على أجهزة التقاط.',
  'camera added.': 'كاميرا أُضيفت.',
  'cameras added.': 'كاميرات أُضيفت.',
  'valid': 'صالح',
  'with errors': 'به أخطاء',
  'Line': 'السطر',
  'Export JSON': 'تصدير JSON',
  'Choose JSON file…': 'اختر ملف JSON…',
  'Or paste JSON': 'أو الصق JSON',
  'Imported': 'استُورد',
  'new': 'جديد',
  'updated': 'محدَّث',
  'The registry lives in this browser. Export it to carry it to another machine; import replaces cameras with the same id and adds the rest.':
    'يعيش السجل في هذا المتصفح. صدّره لنقله إلى جهاز آخر؛ الاستيراد يستبدل الكاميرات ذات المعرّف نفسه ويضيف الباقي.',
  'Search the camera list': 'البحث في قائمة الكاميرات',
  'Focus mode — hide the HUD': 'وضع التركيز — إخفاء الواجهة',
  'This sheet': 'هذه الورقة',
  'stored camera row(s) were unreadable and were dropped on load.':
    'صفوف كاميرات مخزّنة تعذّرت قراءتها وأُسقطت عند التحميل.',
  'The globe needs WebGL, which this browser does not provide.':
    'تحتاج الكرة الأرضية إلى WebGL، وهذا المتصفح لا يوفّره.',
  'Back to the globe': 'العودة إلى الكرة الأرضية',
  'Open the globe': 'فتح الكرة الأرضية',
  'No such camera': 'لا توجد كاميرا بهذا المعرّف',
  'It is not in this browser’s registry — it may have been removed, or registered on another machine.':
    'ليست في سجل هذا المتصفح — ربما أُزيلت، أو سُجّلت على جهاز آخر.',
  'Inspector': 'المفتّش',
  'Capture needs the stream live': 'يحتاج الالتقاط إلى بث مباشر',
  'Apply changes': 'تطبيق التغييرات',
  'detecting': 'جارٍ الكشف',
  'stalled 6 s': 'توقّف 6 ث',
  'The server refused to start detection:': 'رفض الخادم بدء الكشف:',
  'Copy the error': 'نسخ الخطأ',
  'Dismiss': 'إغلاق',
  'Track': 'المسار',
  'Boxes': 'المربعات',
  'Labels': 'التسميات',
  'Tracks': 'المسارات',
  'Drift ghost': 'شبح الانحراف',
  'Freeze frame': 'تجميد الإطار',
  'Unfreeze': 'إلغاء التجميد',
  'Frozen frame': 'إطار مجمّد',
  'Picture in picture': 'صورة داخل صورة',
  'Picture in picture is not supported in this browser': 'صورة داخل صورة غير مدعومة في هذا المتصفح',
  'Detecting': 'جارٍ الكشف',
  'Deck': 'اللوحة السفلية',
  'Detections': 'الاكتشافات',
  'Events': 'الأحداث',
  'Collapse the deck': 'طيّ اللوحة',
  'Expand the deck': 'توسيع اللوحة',
  'Resize the deck': 'تغيير حجم اللوحة',
  'Resize the inspector': 'تغيير حجم المفتّش',
  'All': 'الكل',
  'Export CSV': 'تصدير CSV',
  'No lookup table — detections are counted, not placed.':
    'لا جدول إحداثيات — تُعدّ الاكتشافات ولا تُوضع على الخريطة.',
  'Nothing has happened on this camera yet. Stream, detection and drift events are recorded here.':
    'لم يحدث شيء على هذه الكاميرا بعد. تُسجَّل هنا أحداث البث والكشف والانحراف.',
  'Stream live.': 'البث مباشر.',
  'Stream recovered.': 'عاد البث.',
  'Stream lost — frames stopped arriving (stalled 6 s).':
    'فُقد البث — توقّف وصول الإطارات (توقّف 6 ث).',
  'Source refused:': 'رُفض المصدر:',
  'Connecting…': 'جارٍ الاتصال…',
  'Detection starting.': 'الكشف يبدأ.',
  'Detection running.': 'الكشف يعمل.',
  'Detection stopped.': 'توقّف الكشف.',
  'Detection failed:': 'فشل الكشف:',
  'Start refused:': 'رُفض البدء:',
  'Reference frozen.': 'جُمّد المرجع.',
  'Frame captured': 'التُقط الإطار',
  'Capture failed:': 'فشل الالتقاط:',
  'saved to': 'حُفظ في',
  'Open in project: Projects → From library.': 'افتحه في مشروع: المشاريع ← من المكتبة.',
  'Saved into the live-capture library. Letters, numbers, spaces — the rest is tidied for the filename.':
    'يُحفظ في مكتبة الالتقاط المباشر. حروف وأرقام ومسافات — والباقي يُرتّب لاسم الملف.',
  'Change folder…': 'تغيير المجلد…',
  'Also save to a folder…': 'احفظ نسخة في مجلد أيضًا…',
  'A copy will be saved to:': 'ستُحفظ نسخة في:',
  'all classes': 'كل الفئات',
  'classes': 'فئات',

  // ── the app-status page: the components explained, and the log monitor ──────
  'App status': 'حالة التطبيق',
  'Open app status & logs': 'افتح حالة التطبيق والسجلّات',
  'Every component the app depends on, and the server’s own log — live.':
    'كل مكوّن يعتمد عليه التطبيق، وسجلّ الخادم نفسه — مباشرةً.',
  'System components': 'مكوّنات النظام',
  'The main database — projects, images, GCPs, detections and jobs all live here.':
    'قاعدة البيانات الرئيسية — هنا تُحفظ المشاريع والصور ونقاط الضبط الأرضية وعمليات الكشف والمهام.',
  'In-memory store for caching, rate limiting and job coordination.':
    'مخزن في الذاكرة للتخزين المؤقت وضبط معدّل الطلبات وتنسيق المهام.',
  'File storage for uploaded photos, exports and cached map tiles.':
    'مخزن الملفات للصور المرفوعة والتصديرات وبلاطات الخرائط المخزّنة.',
  'Background workers that run long jobs — ingest, exports, processing.':
    'عمّال الخلفية الذين ينفّذون المهام الطويلة — الاستيراد والتصدير والمعالجة.',
  'The satellite imagery provider the maps fetch their tiles from.':
    'مزوّد صور الأقمار الاصطناعية الذي تجلب الخرائط بلاطاتها منه.',
  'The AI model pipeline. Reported for information only.':
    'خطّ نماذج الذكاء الاصطناعي. يُعرض للمعلومات فقط.',
  'The raster / DEM backend that reads elevation data for geolocation.':
    'المحرّك النقطي / نموذج الارتفاعات الذي يقرأ بيانات الارتفاع لتحديد المواقع.',
  'Required': 'مطلوب',
  'Informational': 'للمعلومات فقط',
  'Up': 'يعمل',
  'Down': 'متوقف',
  'Skipped': 'تم تخطيه',
  'Log monitor': 'مراقب السجلّات',
  'errors': 'أخطاء',
  'warnings': 'تحذيرات',
  'Search logs': 'ابحث في السجلّات',
  'Minimum level': 'الحد الأدنى للمستوى',
  'All levels': 'كل المستويات',
  'Info and above': 'معلومات فما فوق',
  'Warnings and errors': 'التحذيرات والأخطاء',
  'Errors only': 'الأخطاء فقط',
  'Pause the live tail': 'أوقف المتابعة المباشرة مؤقتًا',
  'Resume the live tail': 'استأنف المتابعة المباشرة',
  'Copy the visible lines': 'انسخ السطور الظاهرة',
  'Clear the view — new lines keep arriving': 'امسح العرض — تستمر السطور الجديدة في الوصول',
  'Jump to the newest line': 'انتقل إلى أحدث سطر',
  'End': 'النهاية',
  'Could not fetch logs:': 'تعذّر جلب السجلّات:',
  'Waiting for log entries…': 'بانتظار سطور السجلّ…',
  'No log entries match the current filters.': 'لا توجد سطور سجلّ مطابقة للمرشّحات الحالية.',
  'The server keeps the most recent lines in memory; older lines are dropped. Secrets are scrubbed before they reach this page.':
    'يحتفظ الخادم بأحدث السطور في الذاكرة، وتُحذف السطور الأقدم. تُحجب الأسرار قبل وصولها إلى هذه الصفحة.',

  // ── the add-camera dialog: three questions, not a wall of boxes ─────────────
  'Three things make a camera: a name, its video, and its spot on the map.':
    'ثلاثة أشياء تصنع الكاميرا: اسم، ومصدر الفيديو، وموقعها على الخريطة.',
  'Name the camera': 'سمِّ الكاميرا',
  'e.g. North field gate': 'مثلًا: بوابة الحقل الشمالية',
  'Where does its video come from?': 'من أين يأتي الفيديو؟',
  'Network camera': 'كاميرا شبكة',
  'Plugged into this computer': 'موصولة بهذا الجهاز',
  'Stream address': 'عنوان البث',
  'The address the server will open — an http(s) MJPEG/snapshot URL or rtsp://…':
    'العنوان الذي سيفتحه الخادم — رابط http(s)‎ من نوع MJPEG أو لقطات، أو rtsp://…',
  'Scan again': 'افحص مجددًا',
  'No capture devices found — is the camera plugged in?':
    'لم يُعثر على أجهزة التقاط — هل الكاميرا موصولة؟',
  'Pick a device above — it becomes this camera’s source.':
    'اختر جهازًا في الأعلى — يصبح مصدر هذه الكاميرا.',
  'Where does the camera stand?': 'أين تقف الكاميرا؟',
  'Click its spot on the map — or paste coordinates from Google Maps into either box below.':
    'انقر موقعها على الخريطة — أو الصق الإحداثيات من خرائط Google في أي من الخانتين أدناه.',
  'The map needs an imagery provider — type or paste the coordinates instead.':
    'تحتاج الخريطة إلى مزوّد صور — اكتب الإحداثيات أو الصقها بدلًا من ذلك.',
  'north–south · -90 … 90': 'شمال–جنوب · ‎-90 … 90',
  'east–west · -180 … 180': 'شرق–غرب · ‎-180 … 180',
  'Optional details': 'تفاصيل اختيارية',
  'Compass (°)': 'الاتجاه (°)',
  'View width (°)': 'عرض الرؤية (°)',
  'how wide it sees': 'مدى اتساع ما تراه',
  'frames per second': 'إطارات في الثانية',
  'These only draw the camera’s wedge on the globe — you can add them later.':
    'هذه فقط لرسم مثلث رؤية الكاميرا على الكرة الأرضية — يمكنك إضافتها لاحقًا.',
  'faces': 'تتجه نحو',
  'north': 'الشمال',
  'north-east': 'الشمال الشرقي',
  'east': 'الشرق',
  'south-east': 'الجنوب الشرقي',
  'south': 'الجنوب',
  'south-west': 'الجنوب الغربي',
  'west': 'الغرب',
  'north-west': 'الشمال الغربي',

  // ── the monitor grid + integrations (LAN/HDMI/serial/embedded) ──────────────
  'GRID': 'شبكة',
  'GLOBE': 'الكرة',
  'SIGNAL LOST': 'انقطعت الإشارة',
  'CONNECTING…': 'جارٍ الاتصال…',
  'DATA FEED — NO PICTURE': 'تغذية بيانات — بلا صورة',
  'NO PREVIEW': 'لا معاينة',
  'DATA': 'بيانات',
  'DETECTING': 'يكشف',
  'Stop detection': 'أوقف الكشف',
  'geo': 'الموقع',
  'via': 'عبر',
  'feeds': 'يقدّم',
  'camera + detection data': 'كاميرا + بيانات كشف',
  'detection data': 'بيانات كشف',
  'camera': 'كاميرا',
  'cameras': 'كاميرات',
  'Nothing matches the search.': 'لا شيء يطابق البحث.',
  'LAN': 'شبكة محلية',
  'HDMI / USB': 'HDMI / USB',
  'Serial / UART': 'تسلسلي / UART',
  'Embedded (Pi)': 'نظام مدمج (Pi)',
  'How does it connect?': 'كيف تتصل؟',
  'Network (LAN)': 'شبكة (LAN)',
  'Stream address (optional)': 'عنوان البث (اختياري)',
  'Data feed URL (optional)': 'رابط تغذية البيانات (اختياري)',
  'If the device also SENDS detections (JSON or CSV lines with lat/lon), its points land straight on the map.':
    'إذا كان الجهاز يُرسل أيضًا كشوفات (أسطر JSON أو CSV بإحداثيات)، تهبط نقاطه مباشرة على الخريطة.',
  'Give either or both: video alone → the app runs detection on it; data alone → its points are plotted; both → the picture and the points together.':
    'أعطِ أحدهما أو كليهما: فيديو فقط ← يشغّل التطبيق الكشف عليه؛ بيانات فقط ← تُرسم نقاطها؛ كلاهما ← الصورة والنقاط معًا.',
  'Serial port': 'المنفذ التسلسلي',
  'Baud': 'معدل الباود',
  'A serial connection carries DATA, not video: the device sends detection lines — JSON {"lat":…, "lon":…} or CSV lat,lon,class,score,track — and the app plots each one on the map.':
    'الاتصال التسلسلي يحمل بيانات لا فيديو: يرسل الجهاز أسطر كشف — JSON بإحداثيات أو CSV — ويرسم التطبيق كل سطر نقطةً على الخريطة.',
  'Detection data feed': 'تغذية بيانات الكشف',
  'This integration sends detections instead of video — every line it emits becomes a point on the map.':
    'هذا التكامل يرسل كشوفات بدل الفيديو — كل سطر يصدره يصبح نقطة على الخريطة.',
  'wire': 'الوصلة',
  'received': 'المستلَم',
  'newest': 'الأحدث',
  'lines': 'أسطر',
  'bad': 'تالفة',
  'nothing yet': 'لا شيء بعد',
  'receiving': 'يستقبل',
  'data feed — points land on the map as they arrive':
    'تغذية بيانات — تهبط النقاط على الخريطة فور وصولها',

  // ── recordings: the stream + its attribute table, one folder each ───────────
  'Record': 'تسجيل',
  'REC': 'تسجيل',
  'Record the stream and the detections into the library': 'سجّل البث والكشوفات في المكتبة',
  'Stop recording — the folder gets the video and the CSV':
    'أوقف التسجيل — يحفظ المجلد الفيديو وملف CSV',
  'Recording started.': 'بدأ التسجيل.',
  'Recording saved:': 'حُفظ التسجيل:',
  'Recording saved to the library:': 'حُفظ التسجيل في المكتبة:',
  'One folder per recording — the video as watched, and the detection attribute table as CSV.':
    'مجلد لكل تسجيل — الفيديو كما شوهد، وجدول سمات الكشف كملف CSV.',
  'Download the video': 'نزّل الفيديو',
  'Download the attribute table (CSV)': 'نزّل جدول السمات (CSV)',
  // ── the session package: video + satellite map + table, one folder (2026-09-12) ──
  'Package': 'الحزمة',
  'Download the package': 'نزّل الحزمة',
  'Download the whole package': 'نزّل الحزمة كاملة',
  'video, satellite map and attribute table': 'الفيديو وخريطة الأقمار الصناعية وجدول السمات',
  'Download the satellite map': 'نزّل خريطة الأقمار الصناعية',
  'The video, the satellite map and the attribute table — one folder':
    'الفيديو وخريطة الأقمار الصناعية وجدول السمات — مجلد واحد',
  'Delete this recording': 'احذف هذا التسجيل',
  'Recording deleted:': 'حُذف التسجيل:',
  'Copy the folder path': 'انسخ مسار المجلد',
  'The library could not be read.': 'تعذّرت قراءة المكتبة.',
  'No recordings yet — press Record on a camera while its stream is live.':
    'لا تسجيلات بعد — اضغط «تسجيل» على كاميرا أثناء بثّها المباشر.',

  // ── the camera monitor: the drift watch from the header ─────────────────────
  'Needs the stream live': 'يتطلب أن يكون البث مباشرًا',
  'Retrying automatically — or press Reconnect after replugging.':
    'تُعاد المحاولة تلقائيًا — أو اضغط «إعادة الاتصال» بعد إعادة وصل الكاميرا.',
  'Freeze a reference of what the camera sees now, then check against it — a confirmed move means the lookup table no longer matches the ground.':
    'ثبّت مرجعًا لما تراه الكاميرا الآن، ثم افحص مقابله — الحركة المؤكدة تعني أن جدول الإحداثيات لم يعد يطابق الأرض.',
  'No lookup table is applied yet — drift is measured against the applied table. Apply one in the settings first.':
    'لم يُطبَّق جدول إحداثيات بعد — يُقاس الانحراف مقابل الجدول المطبَّق. طبِّق جدولًا في الإعدادات أولًا.',

  // ── the camera monitor: each camera's setup, remembered ─────────────────────
  'setup saved': 'الإعدادات محفوظة',
  'This camera’s setup is remembered — press Start.': 'إعدادات هذه الكاميرا محفوظة — اضغط ابدأ.',
  'Detection settings': 'إعدادات الكشف',
  'Close the settings panel': 'أغلق لوحة الإعدادات',

  // ── 1.3: the server-side registry, the drift stamp, the centre offset ───────
  'Move your cameras to the server?': 'هل تنقل كاميراتك إلى الخادم؟',
  'This browser holds': 'يحتفظ هذا المتصفح بـ',
  'camera that the server does not know about.': 'كاميرا لا يعرفها الخادم.',
  'cameras that the server does not know about.': 'كاميرات لا يعرفها الخادم.',
  'Since 1.3 the camera list lives on the server, so every machine sees the same cameras and the app can restart their watches after a reboot.':
    'منذ الإصدار 1.3 تُحفظ قائمة الكاميرات على الخادم، فترى كل الأجهزة الكاميرات نفسها ويستطيع التطبيق إعادة تشغيل مراقبتها بعد إعادة التشغيل.',
  'Each camera’s saved detection setup moves with it. This is asked once.':
    'تنتقل إعدادات الكشف المحفوظة لكل كاميرا معها. يُطرح هذا السؤال مرة واحدة.',
  'Forget them': 'انسَها',
  'Move to server': 'انقل إلى الخادم',
  'camera moved to the server.': 'كاميرا نُقلت إلى الخادم.',
  'cameras moved to the server.': 'كاميرات نُقلت إلى الخادم.',
  'The import failed.': 'فشل الاستيراد.',
  'The server refused the camera.': 'رفض الخادم الكاميرا.',
  'The server refused the import.': 'رفض الخادم الاستيراد.',
  'The registry lives on the server, so every machine sees the same cameras. Export it to carry it elsewhere; import updates cameras with a known id and adds the rest.':
    'السجل محفوظ على الخادم، فترى كل الأجهزة الكاميرات نفسها. صدِّره لنقله إلى مكان آخر؛ يحدِّث الاستيراد الكاميرات ذات المعرِّف المعروف ويضيف الباقي.',
  'Centre marks on the object (adds half a vehicle length away from the camera)':
    'مركزة العلامات على الجسم (تُزاح نصف طول المركبة بعيدًا عن الكاميرا)',
  'Steady boxes (smooth and debounce the overlay)': 'مربعات ثابتة (تنعيم العرض ومنع وميض الصناديق)',
  'Export project folder': 'تصدير مجلد المشروع',
  'One folder with the photos, GCPs (CSV), DEM and solve outputs — in your LandExplorer folder.':
    'مجلد واحد يضم الصور ونقاط الضبط الأرضي (CSV) ونموذج الارتفاع ومخرجات الحل — داخل مجلد LandExplorer.',
  'Export folder': 'تصدير المجلد',
  'Exporting…': 'جارٍ التصدير…',
  'Project exported to': 'تم تصدير المشروع إلى',
  'photo(s)': 'صورة',
  'GCP(s)': 'نقطة ضبط',
  'DEM included': 'يتضمن نموذج الارتفاع',
  'no DEM': 'بدون نموذج ارتفاع',
  'LUT(s)': 'جدول بحث',
  'missing': 'مفقود',
  'Camera moved:': 'تحركت الكاميرا:',
  'Optics changed:': 'تغيّرت البصريات:',
  'the marks being placed carry that verdict — their coordinates are in doubt until the camera is re-aimed and the reference re-frozen.':
    'تحمل العلامات الموضوعة هذا الحكم — إحداثياتها موضع شك حتى تُعاد توجيه الكاميرا ويُجمَّد المرجع من جديد.',
  'so far': 'حتى الآن',
  'Drift': 'الانحراف',
  'unwatched': 'غير مراقَب',
  'pending': 'قيد الانتظار',
  'ok': 'سليم',
  'moved': 'تحرك',
  'changed': 'تغيّر',
  'degraded': 'متدهور',

  // ── The server of cameras and its setup pipeline (2026-09-04) ─────────────
  'Camera workspace': 'مساحة الكاميرا',
  'Cameras Monitoring': 'مراقبة الكاميرات',
  'Remove from the server': 'إزالة من الخادم',
  // ── the camera export: the whole camera in one folder (2026-09-12) ──
  'Download the camera settings': 'نزّل إعدادات الكاميرا',
  'Download the settings': 'نزّل الإعدادات',
  'frame, control points, DEM, calibration, lookup table, drift':
    'الإطار، نقاط الضبط، نموذج الارتفاعات، المعايرة، جدول البحث، الانحراف',
  'Everything this camera is: settings, frame, control points, DEM, calibration, lookup table and drift reference':
    'كل ما تمثّله هذه الكاميرا: الإعدادات والإطار ونقاط الضبط ونموذج الارتفاعات والمعايرة وجدول البحث ومرجع الانحراف',
  'Calibration': 'المعايرة',
  'Setup is not finished — the camera can be watched, but its marks cannot be placed on the map yet.':
    'الإعداد لم يكتمل — يمكن مشاهدة الكاميرا، لكن لا يمكن وضع علاماتها على الخريطة بعد.',
  'Settings': 'الإعدادات',
  'Continue setup': 'متابعة الإعداد',
  'was removed from the server.': 'أُزيلت من الخادم.',
  'The server refused the removal.': 'رفض الخادم الإزالة.',
  'No cameras on the server yet': 'لا توجد كاميرات على الخادم بعد',
  'Add the first camera to start: give it a name, say how it connects, attach its DEM and frame, place its control points, and build its lookup table. Every machine that opens this app will then see it.':
    'أضف الكاميرا الأولى للبدء: سمِّها، حدّد طريقة اتصالها، أرفق نموذج الارتفاعات والإطار، ضع نقاط الضبط، وابنِ جدول الإحداثيات. بعدها سيراها كل جهاز يفتح هذا التطبيق.',
  'Add your first camera': 'أضف كاميرتك الأولى',
  'How the pipeline works': 'كيف يعمل مسار الإعداد',
  'every machine sees the same list': 'كل جهاز يرى القائمة نفسها',
  'camera registered': 'كاميرا مسجّلة',
  'cameras registered': 'كاميرات مسجّلة',
  'Registered cameras': 'الكاميرات المسجّلة',
  'Remove this camera?': 'إزالة هذه الكاميرا؟',
  'The camera leaves the server for every machine. Its recorded detections stay; its project, frame and lookup table are kept on disk.':
    'تُزال الكاميرا من الخادم لكل الأجهزة. تبقى اكتشافاتها المسجّلة؛ ويُحتفظ بمشروعها وإطارها وجدول إحداثياتها على القرص.',
  'The lookup table is built and saved to the camera.': 'بُني جدول الإحداثيات وحُفظ في الكاميرا.',
  'Backing project for a registered camera — its DEM, frame and control points.':
    'مشروع داعم لكاميرا مسجّلة — نموذج ارتفاعاتها وإطارها ونقاط ضبطها.',
  'is on the server — continue its setup below.': 'أصبحت على الخادم — تابع إعدادها أدناه.',
  'The frame is saved to the camera — place its control points next.':
    'حُفظ الإطار في الكاميرا — ضع نقاط الضبط الآن.',
  'This connection has no video to capture from — upload a photo instead.':
    'هذا الاتصال لا يحمل فيديو لالتقاط إطار منه — ارفع صورة بدلاً من ذلك.',
  'is saved on the server.': 'حُفظت على الخادم.',
  'This camera is not on the server': 'هذه الكاميرا ليست على الخادم',
  'It may have been removed from another machine.': 'ربما أُزيلت من جهاز آخر.',
  'Back to the camera workspace': 'العودة إلى مساحة الكاميرا',
  'CAMERA WORKSPACE · SETUP PIPELINE': 'مساحة الكاميرا · مسار الإعداد',
  'New camera': 'كاميرا جديدة',
  'Seven steps, top to bottom. The camera is created at step 3; its DEM, frame and lookup table follow.':
    'سبع خطوات من الأعلى إلى الأسفل. تُنشأ الكاميرا في الخطوة 3؛ ثم يأتي نموذج الارتفاعات والإطار وجدول الإحداثيات.',
  'Also the name of its lookup table bundle.': 'وهو أيضاً اسم حزمة جدول إحداثياتها.',
  'Connection type': 'نوع الاتصال',
  'A serial or UART line carries DATA, not video: the device sends detection lines and their points are plotted on the map.':
    'خط تسلسلي أو UART يحمل بيانات لا فيديو: يرسل الجهاز أسطر اكتشاف وتُرسم نقاطها على الخريطة.',
  'Capture cards and cameras on this machine.': 'بطاقات الالتقاط والكاميرات على هذا الجهاز.',
  'FOV / View width (°)': 'مجال الرؤية / عرض المشهد (°)',
  'Create camera and continue': 'أنشئ الكاميرا وتابع',
  'Creates the camera on the server and unlocks the DEM, frame and lookup-table steps.':
    'ينشئ الكاميرا على الخادم ويفتح خطوات نموذج الارتفاعات والإطار وجدول الإحداثيات.',
  'Camera DEM': 'نموذج ارتفاعات الكاميرا',
  'The elevation model every ray from this camera lands on — the lookup table cannot be built without it.':
    'نموذج الارتفاعات الذي يستقر عليه كل شعاع من هذه الكاميرا — لا يمكن بناء جدول الإحداثيات من دونه.',
  'Elevation source': 'مصدر الارتفاع',
  'Prepare the camera’s workspace': 'تجهيز مساحة عمل الكاميرا',
  'Optional data — camera calibration': 'بيانات اختيارية — معايرة الكاميرا',
  'Intrinsics and position. Without fx, fy, cx, cy the camera can still be watched and detections counted, but a lookup table cannot be built.':
    'المعاملات الداخلية والموضع. من دون fx وfy وcx وcy يمكن مشاهدة الكاميرا وعدّ الاكتشافات، لكن لا يمكن بناء جدول الإحداثيات.',
  'Intrinsics (pixels)': 'المعاملات الداخلية (بكسل)',
  'Distortion (Brown–Conrady)': 'التشوّه (Brown–Conrady)',
  'Position above ground': 'الموضع فوق سطح الأرض',
  'Mast height (m)': 'ارتفاع الصاري (م)',
  'metres above the DEM at the camera’s spot': 'أمتار فوق نموذج الارتفاعات عند موقع الكاميرا',
  'Tilt (°)': 'الميل (°)',
  'below horizontal, + = aimed down': 'تحت الأفق، + = موجّهة إلى الأسفل',
  'The frame, and its control points': 'الإطار ونقاط ضبطه',
  'Choose one frame from this camera. Control points are placed on it in the editor; four make the camera measurable.':
    'اختر إطاراً واحداً من هذه الكاميرا. تُوضع نقاط الضبط عليه في المحرّر؛ أربع نقاط تجعل الكاميرا قابلة للقياس.',
  'The camera’s frame': 'إطار الكاميرا',
  'control points placed': 'نقاط ضبط موضوعة',
  'Capture from the camera now': 'التقاط من الكاميرا الآن',
  'Upload a photo': 'رفع صورة',
  'Choose from the capture library': 'اختيار من مكتبة الالتقاط',
  'Review control points': 'مراجعة نقاط الضبط',
  'Opens the editor for this frame. A "Back to camera settings" button there brings you — and the lookup table — back here.':
    'يفتح المحرّر لهذا الإطار. زر «العودة إلى إعدادات الكاميرا» هناك يعيدك — ومعك جدول الإحداثيات — إلى هنا.',
  'One ground coordinate per pixel, solved from the frame, its control points, the calibration and the DEM. The monitoring page places every detection through it, and the drift watch is frozen on the frame the moment the table is built.':
    'إحداثي أرضي واحد لكل بكسل، محسوب من الإطار ونقاط ضبطه والمعايرة ونموذج الارتفاعات. صفحة المراقبة تضع كل اكتشاف من خلاله، وتُجمَّد مراقبة الانحراف على الإطار لحظة بناء الجدول.',
  'max error': 'الخطأ الأقصى',
  'Needed before building': 'مطلوب قبل البناء',
  'a frame': 'إطار',
  'more control point(s)': 'نقطة/نقاط ضبط إضافية',
  'a DEM': 'نموذج ارتفاعات',
  'nothing — build when ready': 'لا شيء — ابنِ عندما تكون جاهزاً',
  'Rebuild lookup table': 'إعادة بناء جدول الإحداثيات',
  'Build lookup table': 'بناء جدول الإحداثيات',
  'Watch this camera': 'مشاهدة هذه الكاميرا',
  'Back to the server': 'العودة إلى الخادم',
  'Save camera': 'حفظ الكاميرا',
  'To do': 'مطلوب',
  'After the camera is created': 'بعد إنشاء الكاميرا',
  'a DEM on the camera': 'نموذج ارتفاعات للكاميرا',
  'Camera setup': 'إعداد الكاميرا',
  'Setting up camera': 'جارٍ إعداد الكاميرا',
  'lookup table': 'جدول الإحداثيات',
  'still needed': 'ما زال مطلوباً',
  'Return with the lookup table': 'العودة مع جدول الإحداثيات',
  'Back to camera settings': 'العودة إلى إعدادات الكاميرا',
  'Building the lookup table': 'جارٍ بناء جدول الإحداثيات',
  // ── home: the workflow board — the two main pages, one step at a time (2026-09-07) ──
  // ── the navbar: three pages, no dropdown; recordings on the Recorded videos page (2026-09-07) ──
  'Pages': 'الصفحات',
  'Register cameras, watch them, and keep what they recorded.':
    'سجّل الكاميرات، وراقبها، واحتفظ بما سجّلته.',
  'What the cameras recorded, and the clips you uploaded — scrub to a moment and keep that frame as a photograph.':
    'ما سجّلته الكاميرات، والمقاطع التي رفعتها — مرّر إلى لحظة واحتفظ بذلك الإطار كصورة.',
  'Camera recordings': 'تسجيلات الكاميرات',
  'Uploaded clips': 'المقاطع المرفوعة',
  'Scrub a recording or an uploaded clip to the moment in Recorded videos and keep that frame as a photograph.':
    'مرّر تسجيلاً أو مقطعاً مرفوعاً إلى اللحظة في الفيديوهات المسجّلة واحتفظ بذلك الإطار كصورة.',
  'Once a camera has its table, every detection lands on the map with real coordinates.':
    'ما إن يصبح للكاميرا جدولها، يستقر كل اكتشاف على الخريطة بإحداثيات حقيقية.',
  'Open the camera on the globe or the wall, apply the detector’s dials, and watch marks land on the map.':
    'افتح الكاميرا على الكرة الأرضية أو الجدار، طبّق إعدادات الكاشف، وراقب العلامات وهي تستقر على الخريطة.',
  'Freeze a reference so the drift watch tells you if the camera moves.':
    'ثبّت مرجعاً ليخبرك مراقب الانحراف إن تحرّكت الكاميرا.',
  'Press Record while it runs — the clip and its attribute table land on the Recorded videos page.':
    'اضغط «تسجيل» أثناء التشغيل — يستقر المقطع وجدول سماته في صفحة الفيديوهات المسجّلة.',
  'Recordings keep a clip of what the camera saw — find them on the Recorded videos page.':
    'تحفظ التسجيلات مقطعاً لما رأته الكاميرا — تجدها في صفحة الفيديوهات المسجّلة.',
  // ── the camera workspace cards: a picture, a meter, one thing to do (2026-09-07) ──
  'Ready': 'جاهزة',
  'In setup': 'قيد الإعداد',
  'ready': 'جاهزة',
  'in setup': 'قيد الإعداد',
  'Live': 'مباشر',
  'Connecting': 'جارٍ الاتصال',
  'Lost': 'مفقودة',
  'Refused': 'مرفوضة',
  'More actions for': 'مزيد من الإجراءات لـ',
  'Setup': 'الإعداد',
  'Next: calibrate the camera': 'التالي: عايِر الكاميرا',
  'Next: choose the frame': 'التالي: اختر الإطار',
  'Next: build the lookup table': 'التالي: ابنِ جدول الإحداثيات',
  'Ready — marks land on the map': 'جاهزة — تستقر العلامات على الخريطة',
  'NO FRAME YET': 'لا إطار بعد',
  'DATA FEED': 'تغذية بيانات',
  'No camera matches.': 'لا كاميرا مطابقة.',
  'Clear filters': 'مسح عوامل التصفية',
  'Show': 'إظهار',
  // ── a recording watched in the app: the player and its table on one clock (2026-09-07) ──
  'Recording': 'تسجيل',
  'Play': 'تشغيل',
  'Back 1 s': 'رجوع ثانية',
  'Forward 1 s': 'تقدّم ثانية',
  'Back one frame': 'رجوع إطاراً',
  'Forward one frame': 'تقدّم إطاراً',
  'Timeline': 'الخط الزمني',
  'Space plays · ← → one second · Shift ← → one frame':
    'المسافة للتشغيل · ← → ثانية · Shift ← → إطار',
  'TRIM': 'قصّ',
  'Selection start': 'بداية التحديد',
  'Selection end': 'نهاية التحديد',
  'Set start here': 'ابدأ من هنا',
  'Set end here': 'انتهِ هنا',
  'Trim to selection': 'قصّ إلى التحديد',
  'Trimming…': 'جارٍ القصّ…',
  'Trimmed clip saved:': 'حُفظ المقطع المقصوص:',
  'The cut is saved as a new recording with the rows of that window — this one stays as it is.':
    'يُحفظ القصّ كتسجيل جديد مع صفوف تلك النافذة — ويبقى هذا التسجيل كما هو.',
  'The video could not be played. The original file can still be downloaded.':
    'تعذّر تشغيل الفيديو. لا يزال بإمكانك تنزيل الملف الأصلي.',
  'This recording has no video — its table still reads.':
    'لا فيديو لهذا التسجيل — لكن جدوله يُقرأ.',
  'Attribute table': 'جدول السمات',
  'rows': 'صفوف',
  'Rows': 'الصفوف',
  'at this moment': 'في هذه اللحظة',
  'Follow playback': 'تتبّع التشغيل',
  'No rows — no detection ran while this was recorded.':
    'لا صفوف — لم يعمل أي كشف أثناء هذا التسجيل.',
  'Time': 'الوقت',
  'Lat': 'خط العرض',
  'Lon': 'خط الطول',
  'Open this recording': 'افتح هذا التسجيل',
  'cut from': 'مقصوص من',
  'Download the table (CSV)': 'تنزيل الجدول (CSV)',
  'No recording selected': 'لم يُحدَّد تسجيل',
  'This page needs a recording in its URL.': 'تحتاج هذه الصفحة إلى تسجيل في عنوانها.',
  'Back to Recorded videos': 'العودة إلى الفيديوهات المسجّلة',
  'This recording isn’t available': 'هذا التسجيل غير متاح',
  'It may have been deleted, or the server could not read its folder.':
    'ربما حُذف، أو تعذّر على الخادم قراءة مجلده.',
  // ── the Recorded videos page as cards (2026-09-07) ──
  'Scrub & capture': 'مرّر والتقط',
  'in scrub & capture': 'في التمرير والالتقاط',
  'Library only': 'المكتبة فقط',
  'No clips uploaded yet': 'لا مقاطع مرفوعة بعد',
  'Recordings': 'التسجيلات',
  'Clips': 'المقاطع',
  'No video': 'لا فيديو',
  'No picture': 'لا صورة',
  'CUT': 'مقصوص',
  'Captured frames': 'الإطارات الملتقطة',
  'Library folder': 'مجلد المكتبة',
  'Folder path copied.': 'نُسخ مسار المجلد.',
  'Delete this recording?': 'حذف هذا التسجيل؟',
  'The folder — its video, its table and its meta — leaves the disk for good.':
    'يغادر المجلد — فيديوه وجدوله وبياناته الوصفية — القرص نهائياً.',
  'No recording matches.': 'لا تسجيل مطابق.',
  'No clip matches.': 'لا مقطع مطابق.',
  'Search recordings and clips': 'ابحث في التسجيلات والمقاطع',
  'What the cameras recorded, and the clips you upload — watch one beside its table, or scrub to a moment and keep the frame.':
    'ما سجّلته الكاميرات، والمقاطع التي ترفعها — شاهد واحداً بجانب جدوله، أو مرّر إلى لحظة واحتفظ بالإطار.',
  'Scrub a clip to the moment and keep that frame as a photograph.':
    'مرّر مقطعاً إلى اللحظة واحتفظ بذلك الإطار كصورة.',
  'A library-only clip keeps its frames in the project chosen at capture time.':
    'يحتفظ مقطع المكتبة فقط بإطاراته في المشروع المختار عند الالتقاط.',
  'No frames captured from this video yet — open scrub & capture and seek to the moment you need.':
    'لم تُلتقط إطارات من هذا الفيديو بعد — افتح التمرير والالتقاط وانتقل إلى اللحظة التي تريدها.',
  'No cameras yet — register one in the camera workspace.':
    'لا كاميرات بعد — سجّل واحدة في مساحة الكاميرا.',
  'No camera is live right now.': 'لا كاميرا مباشرة الآن.',
  'No camera is lost right now.': 'لا كاميرا مفقودة الآن.',
  'no position': 'بلا موضع',
  'THE TWO MAIN PAGES': 'الصفحتان الرئيسيتان',
  'Two pages, step by step': 'صفحتان، خطوة بخطوة',
  'Register a camera in the camera workspace, then watch it on cameras monitoring. Each board walks through its page one step at a time — swipe, use the arrows, or pick a step.':
    'سجّل كاميرا في مساحة الكاميرا، ثم راقبها في مراقبة الكاميرات. كل لوحة تمشي بصفحتها خطوة خطوة — اسحب، أو استخدم الأسهم، أو اختر خطوة.',
  'Quick guide': 'دليل سريع',
  'Step': 'الخطوة',
  'Previous step': 'الخطوة السابقة',
  'Open the page': 'افتح الصفحة',
  'Add the camera': 'أضف الكاميرا',
  'Attach its DEM and calibration': 'أرفق نموذج ارتفاعاتها ومعايرتها',
  'Pick a camera': 'اختر كاميرا',
  'Apply the detector’s dials': 'طبّق إعدادات الكاشف',
  'Watch, and know if it moves': 'راقب، واعرف إن تحرّكت',
  'Export, or keep a recording': 'صدّر، أو احتفظ بتسجيل',
  'Connection': 'الاتصال',
  'Start': 'ابدأ',
  'Steady': 'ثابتة',
  'Fixed cameras, geolocated: register a camera once on the server — its connection, DEM, calibration, frame and lookup table — then watch it, and every detection lands on the map with real coordinates. Runs locally, works offline.':
    'كاميرات ثابتة محدّدة الموقع جغرافياً: سجّل الكاميرا مرة واحدة على الخادم — اتصالها ونموذج ارتفاعاتها ومعايرتها وإطارها وجدول إحداثياتها — ثم راقبها، ويستقر كل اكتشاف على الخريطة بإحداثيات حقيقية. يعمل محلياً ومن دون اتصال.',
  'Register the camera': 'سجّل الكاميرا',
  'In the camera workspace: name it, say how it connects — UTP/LAN, a stream URL, HDMI, USB, BNC, serial, UART or an embedded board — and click its spot on the map.':
    'في مساحة الكاميرا: سمِّها، حدّد طريقة اتصالها — UTP/LAN أو رابط بث أو HDMI أو USB أو BNC أو تسلسلي أو UART أو لوحة مدمجة — وانقر موقعها على الخريطة.',
  'Give it ground truth': 'أعطها مرجعاً أرضياً',
  'Attach the camera’s DEM — its only height source, honest Z, never a guess — and, if you have it, the calibration: intrinsics, mast height, tilt.':
    'أرفق نموذج ارتفاعات الكاميرا — مصدر الارتفاع الوحيد، Z صادق لا تخمين — وإن توفّرت المعايرة: المعاملات الداخلية وارتفاع الصاري والميل.',
  'Frame and control points': 'الإطار ونقاط الضبط',
  'Capture one frame from the camera, pair four of its pixels with map positions in the editor, and build the lookup table — it saves itself to the camera.':
    'التقط إطاراً واحداً من الكاميرا، اربط أربعة من بكسلاته بمواقع على الخريطة في المحرّر، وابنِ جدول الإحداثيات — يُحفظ تلقائياً في الكاميرا.',
  'Watch and detect': 'راقب واكتشف',
  'On cameras monitoring: watch it live, run the detector, see every find land on the map through the table, and be told the moment the camera moves.':
    'في مراقبة الكاميرات: شاهدها مباشرة، شغّل الكاشف، وراقب كل اكتشاف يستقر على الخريطة عبر الجدول، وتلقَّ تنبيهاً لحظة تحرّك الكاميرا.',
  'Open the camera workspace': 'افتح مساحة الكاميرا',
  'Every camera the app knows, registered once on the server: how it connects, where it stands, its DEM, its calibration, the frame its control points sit on, and its lookup table. Every machine sees the same list.':
    'كل كاميرا يعرفها التطبيق، مسجّلة مرة واحدة على الخادم: كيف تتصل، وأين تقف، ونموذج ارتفاعاتها، ومعايرتها، والإطار الذي تقع عليه نقاط ضبطها، وجدول إحداثياتها. كل جهاز يرى القائمة نفسها.',
  'Open cameras monitoring': 'افتح مراقبة الكاميرات',
  'Every registered camera on a globe or a wall of live tiles. Open one to watch it, run detection, see each find land on the map through the camera’s lookup table, and be told when the camera itself has moved.':
    'كل كاميرا مسجّلة على كرة أرضية أو جدار من البلاطات الحية. افتح واحدة لمشاهدتها وتشغيل الاكتشاف ورؤية كل اكتشاف يستقر على الخريطة عبر جدول إحداثيات الكاميرا، وتلقّي تنبيه عندما تتحرك الكاميرا نفسها.',
  'Open the page — with no cameras yet, it asks you to add the first one.':
    'افتح الصفحة — إن لم توجد كاميرات بعد، تطلب منك إضافة الأولى.',
  'Press Add camera: name it, choose the connection (UTP/LAN, stream URL, HDMI, USB, BNC, serial, UART, embedded) and click its spot on the map.':
    'اضغط «إضافة كاميرا»: سمِّها، اختر الاتصال (UTP/LAN، رابط بث، HDMI، USB، BNC، تسلسلي، UART، مدمج) وانقر موقعها على الخريطة.',
  'Create it, then attach the camera’s DEM and, if you have it, its calibration.':
    'أنشئها، ثم أرفق نموذج ارتفاعات الكاميرا، ومعايرتها إن توفّرت.',
  'Choose a frame from the camera and place four control points on it in the editor.':
    'اختر إطاراً من الكاميرا وضع عليه أربع نقاط ضبط في المحرّر.',
  'Build the lookup table — it comes back with you and is saved to the camera. Save, and the camera is ready to watch.':
    'ابنِ جدول الإحداثيات — يعود معك ويُحفظ في الكاميرا. احفظ، وتصبح الكاميرا جاهزة للمشاهدة.',
  'Pick a camera on the globe or the wall — or press Start on a tile to detect with its saved setup.':
    'اختر كاميرا على الكرة الأرضية أو الجدار — أو اضغط «ابدأ» على بلاطة للاكتشاف بإعدادها المحفوظ.',
  'On the camera’s page, apply the detector’s dials; the camera’s lookup table is already selected.':
    'في صفحة الكاميرا، طبّق إعدادات الكاشف؛ جدول إحداثيات الكاميرا محدّد مسبقاً.',
  'Watch marks land on the map, freeze a reference and let the drift watch tell you if the camera moves.':
    'راقب العلامات وهي تستقر على الخريطة، ثبّت مرجعاً ودع مراقب الانحراف يخبرك إن تحرّكت الكاميرا.',
  'Export the detections, or keep a recording for later.':
    'صدّر الاكتشافات، أو احتفظ بتسجيل لوقت لاحق.',
  'UTP / LAN': 'UTP / شبكة محلية',
  'An IP camera on the network — MJPEG or RTSP at a fixed address.':
    'كاميرا IP على الشبكة — MJPEG أو RTSP على عنوان ثابت.',
  'Any http(s) or rtsp:// stream the server can open.':
    'أي بث http(s) أو rtsp:// يمكن للخادم فتحه.',
  'HDMI': 'HDMI',
  'An HDMI capture card plugged into this machine.': 'بطاقة التقاط HDMI موصولة بهذا الجهاز.',
  'USB': 'USB',
  'A USB or USB-C camera plugged into this machine.': 'كاميرا USB أو USB-C موصولة بهذا الجهاز.',
  'BNC': 'BNC',
  'An analogue camera through a BNC capture card on this machine.':
    'كاميرا تناظرية عبر بطاقة التقاط BNC على هذا الجهاز.',
  'Serial': 'تسلسلي',
  'A serial line sending detection data — no picture.':
    'خط تسلسلي يرسل بيانات الاكتشاف — بلا صورة.',
  'UART': 'UART',
  'A UART line (a microcontroller, a Pi header) sending detection data — no picture.':
    'خط UART (متحكّم دقيق، منافذ Pi) يرسل بيانات الاكتشاف — بلا صورة.',
  'A board that streams video, sends detections, or both.':
    'لوحة تبثّ الفيديو أو ترسل الاكتشافات أو كليهما.',
  'Register each camera once — its connection, DEM, calibration, frame and lookup table — and every machine sees it.':
    'سجّل كل كاميرا مرة واحدة — اتصالها ونموذج ارتفاعاتها ومعايرتها وإطارها وجدول إحداثياتها — ويراها كل جهاز.',
  'Every camera on a globe or a wall — open one to watch, measure, detect and capture from it.':
    'كل كاميرا على كرة أرضية أو جدار — افتح واحدة للمشاهدة والقياس والاكتشاف والالتقاط منها.',
  'Camera settings': 'إعدادات الكاميرا',
  'Attach the camera’s DEM': 'أرفق نموذج ارتفاعات الكاميرا',
  'Opens the elevation source: upload a preprocessed DEM, process a new one, or pick one from the library.':
    'يفتح مصدر الارتفاع: ارفع نموذج ارتفاعات معالجاً مسبقاً، أو عالج نموذجاً جديداً، أو اختر واحداً من المكتبة.',
  'Add camera to the server': 'إضافة الكاميرا إلى الخادم',
  'Discard draft': 'تجاهل المسودة',
  'is added to the server.': 'أُضيفت إلى الخادم.',
  'Seven steps, top to bottom — every one open now. The camera joins the server when you press Add camera at the end.':
    'سبع خطوات من الأعلى إلى الأسفل — كلها متاحة الآن. تنضم الكاميرا إلى الخادم عند الضغط على «إضافة الكاميرا» في النهاية.',
  'Seven steps, top to bottom. The frame and the lookup table save as they happen; the rest saves with the button at the end.':
    'سبع خطوات من الأعلى إلى الأسفل. يُحفظ الإطار وجدول الإحداثيات فور حدوثهما؛ والباقي يُحفظ بالزر في النهاية.',
  'Attach the camera’s DEM and, if you have it, its calibration.':
    'أرفق نموذج ارتفاعات الكاميرا، ومعايرتها إن توفّرت.',
  'Build the lookup table — it comes back with you. Press Add camera, and it is on the server, ready to watch.':
    'ابنِ جدول الإحداثيات — يعود معك. اضغط «إضافة الكاميرا» فتصبح على الخادم جاهزة للمشاهدة.',
  'Set up this camera’s map': 'إعداد خريطة هذه الكاميرا',
  'This choice belongs to this camera and shapes every control point placed on its frame. The map loads once you are done. The DEM, the calibration and the position are set on the camera’s settings page.':
    'هذا الاختيار خاص بهذه الكاميرا ويحدّد كل نقطة ضبط توضع على إطارها. تُحمَّل الخريطة عند الانتهاء. يُضبط نموذج الارتفاعات والمعايرة والموضع في صفحة إعدادات الكاميرا.',
  'This choice belongs to this project and shapes every control point in it. The map loads once you are done. The elevation source (DEM) is set in Project settings; the main image and camera live on each photo’s setup page.':
    'هذا الاختيار خاص بهذا المشروع ويحدّد كل نقطة ضبط فيه. تُحمَّل الخريطة عند الانتهاء. يُضبط مصدر الارتفاع (DEM) في إعدادات المشروع؛ والصورة الرئيسية والكاميرا في صفحة إعداد كل صورة.',
  'Add processed DEM to camera settings': 'إضافة نموذج الارتفاعات المعالج إلى إعدادات الكاميرا',
  'Estimate from the field of view': 'تقدير من مجال الرؤية',
  'fx = fy = (frame width / 2) ÷ tan(FOV / 2) — an estimate from the field of view entered at step 3. Replace it with measured values when you have them.':
    'fx = fy = (عرض الإطار / 2) ÷ tan(مجال الرؤية / 2) — تقدير من مجال الرؤية المُدخل في الخطوة 3. استبدله بقيم مقيسة عند توفّرها.',
  'The frame has no focal length yet — the auto estimate and the lookup table need fx and fy. Enter them, or estimate them from the field of view.':
    'لا يملك الإطار بُعداً بؤرياً بعد — التقدير التلقائي وجدول الإحداثيات يحتاجان fx وfy. أدخلهما، أو قدّرهما من مجال الرؤية.',
  'The frame has no focal length yet — the auto estimate and the lookup table need fx and fy. Enter them, or give the field of view at step 3 to estimate them.':
    'لا يملك الإطار بُعداً بؤرياً بعد — التقدير التلقائي وجدول الإحداثيات يحتاجان fx وfy. أدخلهما، أو أعطِ مجال الرؤية في الخطوة 3 لتقديرهما.',
  'calibration (fx, fy)': 'المعايرة (fx، fy)',
  'calibration (fx, fy) on the camera': 'معايرة الكاميرا (fx، fy)',
  'Still needed': 'ما زال مطلوباً',
  'Everything the build needs is in place.': 'كل ما يحتاجه البناء جاهز.',
  'Crop and reproject an elevation model — the terrain every ray from a camera lands on.':
    'قصّ نموذج ارتفاعات وأعد إسقاطه — التضاريس التي يستقر عليها كل شعاع من الكاميرا.',
  'Select a camera': 'اختر كاميرا',
  'Set up the lookup table': 'إعداد جدول الإحداثيات',
  'Manage the camera’s DEM →': 'إدارة نموذج ارتفاعات الكاميرا ←',
  'Choose the frame': 'اختر الإطار',
  'Place control points in the Editor': 'ضع نقاط الضبط في المحرّر',
  'Build the lookup table': 'ابنِ جدول الإحداثيات',
  'Back to the Video editor': 'العودة إلى محرر الفيديو',
  'Every step from a camera on the server to detections on the map — in order, with a door into each. Pick a step on the left; tick it off as you go.':
    'كل خطوة من كاميرا على الخادم إلى اكتشافات على الخريطة — بالترتيب، ولكل خطوة باب. اختر خطوة على اليسار؛ وعلّمها منجزة أثناء تقدّمك.',

  // ── GEO-DRIFT integration (2026-09-04): no calibration, axis angles, field unit ──
  'pan': 'انحراف أفقي',
  'tilt': 'ميل',
  'roll': 'دوران',
  'Pan': 'الانحراف الأفقي',
  'Tilt': 'الميل',
  'Roll': 'الدوران',
  'Field of view (°)': 'مجال الرؤية (°)',
  'a seed for the intrinsics — the true sensor angle':
    'بذرة للمعاملات الداخلية — زاوية المستشعر الحقيقية',
  'This lookup table has no intrinsics — give the camera’s horizontal field of view (degrees) to freeze; the true sensor angle, not a spec sheet’s diagonal.':
    'هذا الجدول بلا معاملات داخلية — أعطِ مجال الرؤية الأفقي للكاميرا (بالدرجات) للتثبيت؛ زاوية المستشعر الحقيقية لا القُطرية من ورقة المواصفات.',
  'frozen on the photograph': 'مثبَّت على الصورة',
  'frozen from the clip': 'مثبَّت من المقطع',
  'frozen from a live grab': 'مثبَّت من لقطة حية',
  'intrinsics from a field of view': 'معاملات داخلية من مجال الرؤية',
  'Field unit bundle': 'حزمة الوحدة الميدانية',
  'No calibration': 'بلا معايرة',
  'No calibration — solve the focal from the control points':
    'بلا معايرة — حلّ البُعد البؤري من نقاط الضبط',
  'Seeded by the field of view at step 3': 'مبدوء من مجال الرؤية في الخطوة 3',
  'Any angle in the right ballpark works — the solve recovers the focal.':
    'أي زاوية تقريبية تكفي — الحل يستعيد البُعد البؤري.',
  'The frame has no focal length yet — the auto estimate and the lookup table need fx and fy. Enter them, or switch on no-calibration mode above.':
    'لا يملك الإطار بُعداً بؤرياً بعد — التقدير التلقائي وجدول الإحداثيات يحتاجان fx وfy. أدخلهما، أو فعّل وضع «بلا معايرة» أعلاه.',
  'calibration (fx, fy — or no-calibration mode)': 'المعايرة (fx وfy — أو وضع «بلا معايرة»)',

  // ── the drift watch is the camera's, frozen on its frame (2026-09-08) ────────
  'Runs with detection. Click a detected object to follow it; double-click to lock it.':
    'يعمل مع الكشف. انقر على جسم مكتشَف لتتبّعه؛ انقر مرتين لتثبيته.',
  'Objects being followed — click one in the video to release it':
    'أجسام قيد التتبّع — انقر على أحدها في الفيديو لتحريره',
  'The drift reference is made in the camera settings: capture the frame, place its control points and build the lookup table — the watch starts on that frame.':
    'يُنشأ مرجع الانحراف في إعدادات الكاميرا: التقط الإطار، ضع نقاط ضبطه وابنِ جدول الإحداثيات — تبدأ المراقبة على ذلك الإطار.',
  'Watching live from the frozen frame — the first look has not run yet.':
    'مراقبة حيّة من الإطار المجمّد — لم تُجرَ النظرة الأولى بعد.',
  'The reference is frozen but its watch is not running.': 'المرجع مجمّد لكن مراقبته لا تعمل.',
  'Re-freeze from a new frame in the camera settings':
    'إعادة التجميد من إطار جديد في إعدادات الكاميرا',
  'Open the camera settings': 'فتح إعدادات الكاميرا',
  'not frozen yet — capture the frame, place its control points and build the lookup table in the camera settings':
    'لم يُجمَّد بعد — التقط الإطار، ضع نقاط ضبطه وابنِ جدول الإحداثيات في إعدادات الكاميرا',
  'not frozen yet — the reference is made from the frame in the camera settings':
    'لم يُجمَّد بعد — يُنشأ المرجع من الإطار في إعدادات الكاميرا',
  'reference frozen — the watch is not running; re-freeze from a new frame in the camera settings':
    'المرجع مجمّد — المراقبة لا تعمل؛ أعد التجميد من إطار جديد في إعدادات الكاميرا',
  'watching live from the frozen frame — no look has run yet':
    'مراقبة حيّة من الإطار المجمّد — لم تُجرَ أي نظرة بعد',
  'Drift reference frozen on the frame': 'جُمِّد مرجع الانحراف على الإطار',
  'Drift reference frozen on this frame': 'مرجع الانحراف مجمّد على هذا الإطار',
  'watching in the background': 'مراقبة في الخلفية',
  'checking the watch…': 'جارٍ التحقّق من المراقبة…',
  'the watch is not running': 'المراقبة لا تعمل',
  'The drift reference is not frozen yet.': 'لم يُجمَّد مرجع الانحراف بعد.',
  'The drift watch starts on this frame once the lookup table is built (step 7).':
    'تبدأ مراقبة الانحراف على هذا الإطار بمجرد بناء جدول الإحداثيات (الخطوة 7).',
  'Freeze on this frame': 'تجميد على هذا الإطار',
  'Re-freeze on this frame': 'إعادة التجميد على هذا الإطار',
  'Freezing…': 'جارٍ التجميد…',
  'The drift reference could not be frozen:': 'تعذّر تجميد مرجع الانحراف:',

  // ── the default focal seed (2026-09-09) ────────────────────────────────────
  'calibration on the camera (fx, fy — or no-calibration mode)':
    'معايرة الكاميرا (fx وfy — أو وضع «بلا معايرة»)',
  'No field of view at step 3 — the solve starts from a default 60° seed, which covers roughly 37°–125°.':
    'لا مجال رؤية في الخطوة 3 — يبدأ الحل من بذرة افتراضية 60° تغطي تقريباً من 37° إلى 125°.',
  'Type the camera’s field of view at step 3 only for a telephoto or an ultra-wide lens — the true sensor angle, not a spec sheet’s diagonal figure.':
    'أدخل مجال رؤية الكاميرا في الخطوة 3 فقط لعدسة مقرِّبة أو فائقة الاتساع — زاوية المستشعر الحقيقية لا الرقم القُطري من ورقة المواصفات.',
  'Focal solved from the control points': 'البُعد البؤري محلول من نقاط الضبط',
  'Focal taken from the seed — the solve could not improve on it':
    'أُخذ البُعد البؤري من البذرة — لم يستطع الحل تحسينه',
  'field of view': 'مجال رؤية',
  'seed': 'بذرة',
  'default': 'افتراضي',

  // ── the live capture dialog: choose the frame from inside the camera (2026-09-09) ──
  'Capture a frame from the camera': 'التقاط إطار من الكاميرا',
  'The captured frame': 'الإطار الملتقَط',
  'The live picture. Press “Capture this frame” at the moment you want.':
    'الصورة الحيّة. اضغط «التقاط هذا الإطار» في اللحظة التي تريدها.',
  'This is the frame that was captured. Use it as the camera’s frame, or go back to the live picture and try again.':
    'هذا هو الإطار الذي التُقط. استخدمه إطاراً للكاميرا، أو عُد إلى الصورة الحيّة وحاول مجدداً.',
  'Capture this frame': 'التقاط هذا الإطار',
  'Use this frame': 'استخدام هذا الإطار',
  'Live picture': 'الصورة الحيّة',
  'The stream could not be opened.': 'تعذّر فتح البث.',

  // ── a new frame over one with control points: has the camera moved? (2026-09-09) ──
  'Has the camera moved?': 'هل تحرّكت الكاميرا؟',
  'The current frame has {n} control points.': 'يحمل الإطار الحالي {n} نقطة ضبط.',
  'What happens to them depends on whether the camera still looks exactly where it did.':
    'ما يحدث لها يعتمد على ما إذا كانت الكاميرا لا تزال تنظر إلى المكان نفسه تماماً.',
  'No — same aim': 'لا — التوجيه نفسه',
  'Yes — it moved': 'نعم — تحرّكت',
  'The control points are carried over at the same pixels, the lookup table stays, and the drift reference refreshes on the new frame.':
    'تُنقل نقاط الضبط عند البكسلات نفسها، ويبقى جدول الإحداثيات، ويتجدّد مرجع الانحراف على الإطار الجديد.',
  'The control points are carried over at the same pixels.': 'تُنقل نقاط الضبط عند البكسلات نفسها.',
  'The points start afresh on the new frame, and the lookup table is detached — it was solved for the old aim and must be rebuilt.':
    'تبدأ النقاط من جديد على الإطار الجديد، ويُفصل جدول الإحداثيات — فقد حُلّ للتوجيه القديم ويجب إعادة بنائه.',
  'The points start afresh on the new frame.': 'تبدأ النقاط من جديد على الإطار الجديد.',
  'The control points could not be carried over:': 'تعذّر نقل نقاط الضبط:',
  'The frame is saved to the camera — {n} control points carried over.':
    'حُفظ الإطار في الكاميرا — نُقلت {n} نقطة ضبط.',
  'The frame is saved to the camera. The lookup table was detached — place the control points and rebuild it.':
    'حُفظ الإطار في الكاميرا. فُصل جدول الإحداثيات — ضع نقاط الضبط وأعد بناءه.',
  'Built from an earlier frame of this camera — kept because the aim is the same. Rebuild it to solve on the current frame.':
    'بُني من إطار سابق لهذه الكاميرا — أُبقي لأن التوجيه نفسه. أعد بناءه ليُحلّ على الإطار الحالي.',

  // ── the measured shift on the ground (2026-09-09) ─────────────────────────
  'Shift on the ground': 'الإزاحة على الأرض',
  'at': 'عند',

  // ── the setup table (2026-09-10) ───────────────────────────────────────────
  'SETUP STATUS': 'حالة الإعداد',
  '{filled} of {total} rows filled': 'اكتمل {filled} من {total} صفوف',
  'Setup complete — the camera is measurable.': 'اكتمل الإعداد — الكاميرا جاهزة للقياس.',
  'Next:': 'التالي:',
  'Rows filled': 'الصفوف المكتملة',
  'Fill the rows top to bottom. The camera joins the server when you press Add camera at the end.':
    'املأ الصفوف من الأعلى إلى الأسفل. تنضم الكاميرا إلى الخادم عند الضغط على «إضافة الكاميرا» في النهاية.',
  'The frame and the lookup table save as they happen; the rest saves with the button at the end.':
    'يُحفظ الإطار وجدول الإحداثيات فور إنجازهما؛ ويُحفظ الباقي بالزر في النهاية.',
  'FILL IN': 'التعبئة',
  'STATUS': 'الحالة',
  'Filled': 'مكتمل',
  'Optional — empty': 'اختياري — فارغ',
  'Not filled': 'غير مكتمل',
  'DEM attached': 'نموذج الارتفاع مرفق',
  'Calibration typed': 'المعايرة مُدخلة',
  '60° seed': 'بذرة 60°',
  'control points': 'نقاط ضبط',
  'Ready to build': 'جاهز للبناء',

  // ── live predict on the monitoring page (2026-09-10) ───────────────────────
  'Predict': 'تنبّؤ',
  'Point at the picture': 'وجّه المؤشر إلى الصورة',
  'Outside the table': 'خارج جدول الإحداثيات',
  'Sky, or ground the table does not cover': 'سماء، أو أرض لا يغطيها الجدول',
  'Copy the coordinates (c)': 'انسخ الإحداثيات (c)',
  'Copy the coordinates': 'انسخ الإحداثيات',
  'Pinned — click the picture to release': 'مثبّت — انقر الصورة لتحريره',
  'Nothing to copy yet — point at the ground first.':
    'لا شيء للنسخ بعد — وجّه المؤشر إلى الأرض أولًا.',
  'A correspondence is open — place it or cancel it first.':
    'ثمة اقتران مفتوح — ضعه أو ألغِه أولًا.',
  'Start a new ground control point: a photo click, then a map click.':
    'ابدأ نقطة ضبط أرضية جديدة: نقرة على الصورة ثم نقرة على الخريطة.',
  'Reset zoom': 'إعادة ضبط التكبير',
  'Missing:': 'ينقصها:',

  // ── the information dashboard, the globe search, borders and names (2026-09-10) ──
  'Hide borders and names': 'أخفِ الحدود والأسماء',
  'Show borders and names': 'أظهر الحدود والأسماء',
  'Searching online…': 'جارٍ البحث عبر الإنترنت…',
  'No place found': 'لم يُعثر على مكان',
  'City, country, region — or lat, lon': 'مدينة، دولة، منطقة — أو خط العرض، خط الطول',
  'Search places or coordinates': 'ابحث عن مكان أو إحداثيات',
  'Continent': 'قارة',
  'Region': 'منطقة',
  'Country': 'دولة',
  'Province': 'محافظة',
  'City': 'مدينة',
  'Coordinates': 'إحداثيات',
  'Online result': 'نتيجة من الإنترنت',
  'Server': 'الخادم',
  'up for': 'يعمل منذ',
  'What this installation holds, and how it is doing.': 'ما يحتويه هذا التثبيت، وكيف حاله.',
  'live now': 'مباشر الآن',
  'projects': 'مشاريع',
  'lookup tables': 'جداول إحداثيات',
  'Fleet': 'الأسطول',
  'Cameras by live state': 'الكاميرات حسب حالة البث',
  'not opened yet': 'لم تُفتح بعد',
  'Setup pipeline': 'مسار الإعداد',
  'Cameras that have each setup output': 'الكاميرات التي أنجزت كل مخرج من الإعداد',
  'Every camera is measurable.': 'كل الكاميرات جاهزة للقياس.',
  'camera(s) still need their lookup table.': 'كاميرا/كاميرات ما زالت تحتاج جدول الإحداثيات.',
  'cameras watched': 'كاميرات مراقبة',
  'frozen references': 'مراجع مجمّدة',
  'Watched cameras by latest verdict': 'الكاميرات المراقبة حسب آخر حكم',
  'recordings': 'تسجيلات',
  'of video': 'من الفيديو',
  'on disk': 'على القرص',
  'marks recorded': 'علامات مسجّلة',
  'Recordings started per day, last 14 days': 'التسجيلات التي بدأت يوميًا، آخر 14 يومًا',
  'The server did not answer the readiness check.': 'لم يُجب الخادم على فحص الجاهزية.',
  'Offline imagery': 'صور بلا اتصال',
  'Cache an area': 'خزّن منطقة',
  'cached areas': 'مناطق مخزّنة',
  'tiles on disk': 'بلاطات على القرص',
  'Areas are cached from the globe on the monitoring page: draw the area, pick the zoom band, download.':
    'تُخزَّن المناطق من الكرة الأرضية في صفحة المراقبة: ارسم المنطقة، اختر نطاق التكبير، ثم نزّل.',
  'System': 'النظام',
  'Drift watch running': 'مراقبة الانحراف تعمل',
  'Drift watch paused. The reference stays frozen.':
    'أُوقفت مراقبة الانحراف مؤقتًا. يبقى المرجع مجمّدًا.',
  'watching': 'تراقب',
  'paused': 'متوقفة مؤقتًا',
  'The reference is frozen on the frame the control points sit on, and the camera is checked against it in the background. Moved, changed or degraded is stamped on every mark.':
    'يُجمَّد المرجع على الإطار الذي تقع عليه نقاط الضبط، وتُفحص الكاميرا مقابله في الخلفية. يُختم كل علامة بـ«تحرّكت» أو «تغيّرت» أو «متدهور».',
  'Available once the camera is added: its reference freezes the moment the lookup table is built.':
    'متاح بعد إضافة الكاميرا: يُجمَّد مرجعها لحظة بناء جدول الإحداثيات.',
  'Check every': 'افحص كل',
  'Pause the watch': 'أوقف المراقبة مؤقتًا',
  'Resume the watch': 'استأنف المراقبة',
  'Open the drift monitor': 'افتح مراقب الانحراف',
  'Show later': 'أظهره لاحقًا',
  'Don’t show again': 'لا تُظهره مجددًا',
  'Close this warning': 'أغلق هذا التحذير',
  'GRAZING GEOMETRY': 'هندسة الرؤية المائلة',
  'Max shift (m)': 'أقصى إزاحة (م)',
  'DTM sigma (m)': 'انحراف نموذج الارتفاع (م)',
  'Max sigma (m)': 'أقصى انحراف (م)',
  'The last run used': 'استخدم التشغيل الأخير',
  'A match larger than the max shift is refused as a false lock — 25 m suits a drone and censors a ground camera’s real errors. Max sigma drops tiles the terrain model cannot support; at 0 it keeps every tile and just reports how much each one is worth.':
    'تُرفض أي مطابقة أكبر من أقصى إزاحة باعتبارها قفلًا خاطئًا — 25 م تناسب الطائرة المسيّرة وتحجب أخطاء الكاميرا الأرضية الحقيقية. «أقصى انحراف» يستبعد البلاطات التي لا يدعمها نموذج التضاريس؛ وعند 0 يُبقيها جميعًا ويكتفي بالإبلاغ عن قيمة كل واحدة.',
  'Affine third chance — recovers tiles that are sheared by terrain-height error rather than merely shifted. It only ever adds tiles, but it changes which ground is measured, so a run with it on is not comparable with one without.':
    'فرصة ثالثة تآلفية — تستعيد البلاطات المشوّهة بفعل خطأ ارتفاع التضاريس لا المزاحة فحسب. تضيف بلاطات فقط، لكنها تغيّر أي أرض تُقاس، فلا يُقارن تشغيل مُفعَّل بآخر غير مُفعَّل.',
  'Tile size from the scene — overrides the tile and stride above. A large tile holds more texture; a small one spans less change in amplification.':
    'حجم البلاطة من المشهد — يتجاوز البلاطة والخطوة أعلاه. البلاطة الكبيرة تحمل نسيجًا أكثر؛ والصغيرة تمتد عبر تغيّر أقل في التضخيم.',
  'no data': 'لا بيانات',
  'tiles': 'بلاطة',
  'median error vs satellite': 'الخطأ الوسيط مقابل الأقمار الصناعية',
  'Error zones': 'مناطق الخطأ',
  'Error zones on the photograph — where the last measurement found the geolocation weak':
    'مناطق الخطأ على الصورة — حيث وجد القياس الأخير التحديد الجغرافي ضعيفًا',
  'Three range bands by three columns. Each zone carries the median error the last measurement found inside it, and how many tiles that number rests on. Compare zones against each other: a whole band worse than the rest points at the terrain model or the focal length; one column worse points at the pose.':
    'ثلاثة نطاقات مدى في ثلاثة أعمدة. تحمل كل منطقة الخطأ الوسيط الذي وجده القياس الأخير داخلها، وعدد البلاطات التي يستند إليها هذا الرقم. قارن المناطق ببعضها: نطاق كامل أسوأ من البقية يشير إلى نموذج التضاريس أو البعد البؤري؛ وعمود واحد أسوأ يشير إلى وضعية الكاميرا.',
  'Show them on the photograph': 'أظهرها على الصورة',
  'Fill opacity': 'عتامة التعبئة',
  'Zone fill opacity': 'عتامة تعبئة المناطق',
  'tile': 'بلاطة',
  'Raise the reach to cover the scene — when the max range above leaves under 85% of the visible ground inside it, the run reaches to the far edge of what the camera sees. A drone flight that already covers its view is left exactly as set.':
    'ارفع المدى ليغطي المشهد — عندما يترك أقصى المدى أعلاه أقل من 85% من الأرض المرئية داخله، يصل التشغيل إلى الحافة البعيدة لما تراه الكاميرا. رحلة الطائرة المسيّرة التي تغطي مشهدها أصلًا تُترك كما ضُبطت تمامًا.',
  'The last run raised it from': 'رفعه التشغيل الأخير من',
  'to': 'إلى',
  'Cloud mask — leaves cloud in the satellite imagery out of the match. A lock on a cloud edge is not a geolocation error, and the neighbour check cannot catch one. Off by default: bright white roofs can be taken for cloud.':
    'قناع السحب — يستبعد السحب في صور الأقمار الصناعية من المطابقة. القفل على حافة سحابة ليس خطأ تحديد جغرافي، وفحص الجوار لا يلتقطه. مُعطّل افتراضيًا: الأسطح البيضاء الساطعة قد تُحسب سحبًا.',
  'The last run found': 'وجد التشغيل الأخير',
  'locked tile on cloud': 'بلاطة مقفلة على سحابة',
  'locked tiles on cloud': 'بلاطات مقفلة على سحب',
  'of the content': 'من المحتوى',
  'All tracks': 'كل المسارات',
  'Track name': 'اسم المسار',
  'Rename track': 'إعادة تسمية المسار',
  'Track box': 'تتبّع بإطار',
  'Draw a box to track': 'ارسم إطارًا للتتبّع',
  'Drag a box around the object to track it': 'اسحب إطارًا حول الجسم لتتبّعه',
  'tracking': 'يتتبّع',
  'ViT — learned, steadiest': 'ViT — متعلَّم، الأكثر ثباتًا',
  'USB / capture card': 'USB / بطاقة التقاط',
  'An IP camera or a board (Pi) on the network — video at an address, detection data, or both.':
    'كاميرا IP أو لوحة (Pi) على الشبكة — فيديو على عنوان، أو بيانات كشف، أو كلاهما.',
  'A camera or capture card plugged into this machine — USB, HDMI or BNC.':
    'كاميرا أو بطاقة التقاط موصولة بهذا الجهاز — USB أو HDMI أو BNC.',
  'A serial or UART line sending detection data — no picture.':
    'خط تسلسلي أو UART يرسل بيانات الكشف — بلا صورة.',
  'Protocol': 'البروتوكول',
  'Video protocol': 'بروتوكول الفيديو',
  'Data feed protocol': 'بروتوكول تغذية البيانات',
  'Video address': 'عنوان الفيديو',
  'Data feed (optional)': 'تغذية البيانات (اختياري)',
  'Host, port and path — the protocol is the box on the left. Leave it empty if this device only sends detection data.':
    'المضيف والمنفذ والمسار — البروتوكول في الحقل المجاور. اتركه فارغًا إذا كان هذا الجهاز يرسل بيانات الكشف فقط.',
  'If the device also SENDS detections (JSON or CSV lines with lat/lon), its points land straight on the map. http(s) is polled; ws(s) and tcp are pushed by the sender.':
    'إذا كان الجهاز يرسل أيضًا عمليات الكشف (أسطر JSON أو CSV تحمل خط العرض والطول)، تهبط نقاطه مباشرة على الخريطة. http(s) يُستعلَم عنه؛ أما ws(s) وtcp فيدفعهما المرسِل.',
  'Press Add camera: name it, choose how it connects (UTP/LAN for an IP camera or a board, USB for a capture card, serial/UART for a data line) and click its spot on the map.':
    'اضغط «إضافة كاميرا»: سمِّها، اختر طريقة اتصالها (UTP/LAN لكاميرا IP أو لوحة، وUSB لبطاقة التقاط، وتسلسلي/UART لخط بيانات) وانقر موقعها على الخريطة.',
  'Press Add camera: name it, choose the connection (UTP/LAN for an IP camera or a board, USB for a capture card, serial/UART for a data line) and click its spot on the map.':
    'اضغط «إضافة كاميرا»: سمِّها، اختر الاتصال (UTP/LAN لكاميرا IP أو لوحة، وUSB لبطاقة التقاط، وتسلسلي/UART لخط بيانات) وانقر موقعها على الخريطة.',
  'In the camera workspace: name it, say how it connects — UTP/LAN for an IP camera or a board, USB for a capture card, serial/UART for a data line — and click its spot on the map.':
    'في مساحة الكاميرا: سمِّها، وحدّد طريقة اتصالها — UTP/LAN لكاميرا IP أو لوحة، وUSB لبطاقة التقاط، وتسلسلي/UART لخط بيانات — وانقر موقعها على الخريطة.',
  'Marks': 'العلامات',
  '1 per second': 'واحدة في الثانية',
  '2 per second': 'اثنتان في الثانية',
  '5 per second': 'خمس في الثانية',
  'Every frame': 'كل إطار',
  'Per object, not per run.': 'لكل جسم، لا لكل تشغيل.',
  'Marks per object': 'العلامات لكل جسم',
  'Every detection is still counted and recorded — this thins the map.':
    'كل عملية كشف تُحتسب وتُسجَّل — هذا يخفّف الخريطة فقط.',
};
