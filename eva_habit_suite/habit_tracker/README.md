# Habit Tracker — V2 Redesign

تطبيق سطح مكتب أوفلاين بالكامل مبني بـ **PyQt6 + matplotlib + SQLite**.

## التشغيل

```bash
pip install -r requirements.txt
python main.py
```

أول تشغيل ينشئ `habit_tracker.db` محليًا بجانب البرنامج. لا يوجد اعتماد على الإنترنت أثناء استخدام التطبيق.

## ما تم تعديله في V2

### 🎨 Redesign محافظ على الواجهة الأصلية
- حافظت على فكرة **الهيدر + لوحة التحليلات اليسار + جدول العادات الرئيسي** بدل تحويل التطبيق بالكامل إلى شكل مختلف.
- قللت الزحمة في الهيدر بتقسيم عناصر التنقل عن أزرار الإجراءات.
- حسّنت المسافات، أحجام الخطوط، حدود الأزرار، وحالات الـ hover/pressed.
- قللت عرض لوحة التحليلات قليلًا لإعطاء جدول العادات مساحة أكبر.
- حسّنت شكل الجدول والـ controls ليكونوا أوضح على الشاشات الكبيرة.

### 🌊 Animated Background
- تمت إضافة خلفية متحركة خفيفة تعمل محليًا باستخدام `QPainter` و`QTimer`.
- الخلفية تحتوي على تدرج ناعم ودوائر ضوئية وجزيئات تتحرك ببطء خلف الواجهة.
- تتغير ألوانها تلقائيًا مع الـ theme الحالي.
- الحركة مقصودة أن تكون subtle حتى لا تشتت المستخدم أثناء تسجيل العادات.
- لا توجد صور خارجية أو WebView أو اتصال إنترنت مطلوب.

### 🔎 Habit Search
- أضفت مربع بحث سريع أعلى الجدول.
- البحث يعمل على اسم العادة والفئة، ويُحدّث الجدول والتحليلات فورًا.
- يوجد Clear button لمسح البحث بسرعة.

### 📅 Today
- زر **Today** يرجع مباشرة إلى الشهر والسنة الحاليين.
- عند تشغيل التطبيق يتم ضبط Month/Year selectors على تاريخ النظام الحالي بدل أي حالة قديمة من الواجهة.

### 🐛 إصلاحات التاريخ والإحصائيات
- إصلاح مشكلة ظهور سنوات قديمة مثل 2020/2021 كأنها السنة الحالية.
- العادات القديمة التي لا تملك `created_at` يتم استنتاج تاريخ إنشائها من أقدم log حقيقي لها، بدل استخدام تاريخ افتراضي قديم.
- الإحصائيات لا تحسب الأيام قبل إنشاء العادة.
- الأيام المستقبلية لا تدخل في نسب الإنجاز أو الـ missed days.
- الـ current/best streak يأخذ تاريخ إنشاء العادة في الاعتبار.

## المميزات الموجودة أصلًا

- Dark / Light / Paper / Ocean themes.
- Month View وWeek View.
- Category filtering.
- تعديل اسم العادة، target، النوع، الوحدة، الهدف اليومي، اللون والفئة.
- Check habits وNumeric habits.
- Daily Mood + Daily Notes.
- Drag & Drop لترتيب العادات.
- Review Missed Days.
- Finish Month + Yearly Progress.
- XP / Levels / Achievements.
- Daily celebration toast.
- Daily reminders + System Tray.
- Arabic / English.
- Profile + live clock حسب timezone المختار.

## بناء نسخة Windows EXE

يوجد ملف `build_windows.bat` جاهز للبناء باستخدام PyInstaller:

```bat
build_windows.bat
```

سيتم إنشاء البرنامج في:

`dist\HabitTracker\HabitTracker.exe`

**مهم:** ملف البناء مخصص للتنفيذ على Windows، ولم يتم تشغيل PyInstaller/EXE داخل بيئة العمل الحالية لأنها Linux ولا تحتوي PyQt6 مثبتًا أو اتصال إنترنت لتثبيت dependencies.

## حالة الاختبار

- `python -m py_compile main.py` ✅
- فحص تعديلات قاعدة البيانات والمنطق الأساسي تم إجراؤه في النسخة السابقة من المشروع.
- تشغيل GUI فعليًا في بيئة العمل الحالية ❌ بسبب غياب `PyQt6` وعدم توفر اتصال إنترنت لتثبيته.
- لذلك لا أعتبر الـ GUI runtime/Windows EXE مختبرًا 100% هنا، ولن أدّعي ذلك حتى يتم تشغيله على بيئة Windows فيها dependencies.


## V5 planner updates
- Animated background is visible behind translucent content.
- AM/PM clock and time controls.
- Windows alarm sound for reminders.
- Planner supports appointments, deliveries, deadlines, notes, completion, and alarms.
- Notebook UI refreshed with search, pinning, categories, larger editor, and cleaner cards.
