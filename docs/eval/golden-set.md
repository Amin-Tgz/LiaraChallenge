# Golden Evaluation Set

این مجموعه مستقیماً با مستندات عمومی لیارا تطبیق داده شده است. URLهای بخش `expected_sources` مسیرهای واقعی و قابل دسترس مستندات هستند.

| نوع | سؤال‌ها | تعداد |
|---|---|:---:|
| ساده و مستقیم | Q1–Q3 | 3 |
| چندمرحله‌ای / پیچیده | Q4–Q5 | 2 |
| دارای متن خطا | Q6–Q7 | 2 |
| مبهم و نیازمند سؤال تکمیلی | Q8–Q9 | 2 |
| خارج از اطلاعات مستندات | Q10 | 1 |

---

## Q1

**question:** چطور متغیر محیطی `DATABASE_URL` را از پنل لیارا برای برنامه‌ام تنظیم یا ویرایش کنم؟

**expected_answer_points:**

- در کنسول لیارا وارد برنامه شود
- از بخش تنظیمات وارد بخش متغیرها شود
- متغیر `DATABASE_URL` و مقدار آن را اضافه یا ویرایش کند
- تغییرات را ثبت کند

**expected_sources:**

- [https://docs.liara.ir/paas/details/envs/](https://docs.liara.ir/paas/details/envs/)

**expected_clarification:** none

**expected_abstention:** false

**difficulty:** easy

**tags:** service=paas, runtime=any, framework=any

**notes:** پاسخ کوتاه و مبتنی بر مسیر داخل Console باشد؛ مقدار واقعی یا نمونه‌ی حاوی Secret ساخته نشود

---

## Q2

**question:** یه دامنه خریدم؛ چطور وصلش کنم به برنامه‌ام روی لیارا؟

**expected_answer_points:**

- در برنامه از منوی دامنه‌ها گزینه افزودن دامنه را انتخاب کند
- نام دامنه را وارد و گزینه ایجاد دامنه را بزند
- سه رکورد ارائه‌شده را در DNS تنظیم کند: `ALIAS / CNAME`، رکورد `TXT` و رکورد `CNAME (DNS-01 Challenge)`
- پس از انتشار رکوردها گزینه بررسی وضعیت رکوردها را بزند
- سبز شدن وضعیت رکوردها نشانه اتصال موفق دامنه است

**expected_sources:**

- [https://docs.liara.ir/paas/domains/add-domain/](https://docs.liara.ir/paas/domains/add-domain/)

**expected_clarification:** none

**expected_abstention:** false

**difficulty:** easy

**tags:** service=paas, runtime=any, framework=any

**notes:** در صورت نمایش رسانه، تصویر وضعیت رکوردهای فعال با متن جایگزین مناسب مفید است

---

## Q3

**question:** فایل‌سیستم برنامه Python من روی لیارا به‌صورت پیش‌فرض writable است؟ برای فایل موقت کجا می‌تونم بنویسم؟

**expected_answer_points:**

- فایل‌سیستم برنامه Python به‌صورت پیش‌فرض `ReadOnly` است
- دایرکتوری `/tmp` از حالت فقط‌خواندنی مستثنا است
- فضای پیش‌فرض `/tmp` برابر ۱۰۰ مگابایت است
- `/tmp` برای لاگ‌ها و فایل‌های آپلودی موقتی مناسب است
- برای داده‌ای که نباید حذف شود باید از دیسک استفاده شود

**expected_sources:**

- [https://docs.liara.ir/paas/details/file-system/](https://docs.liara.ir/paas/details/file-system/)

**expected_clarification:** none

**expected_abstention:** false

**difficulty:** easy

**tags:** service=paas, runtime=python, framework=any

**notes:** بین فضای writable موقت و دیسک پایدار تمایز روشن ایجاد شود

---

## Q4

**question:** می‌خوام با هر push روی branch اصلی، GitHub Actions برنامه‌ام رو خودکار روی لیارا deploy کنه. چه فایل و Secretهایی لازم دارم؟

**expected_answer_points:**

- یک workflow در مسیر `.github/workflows/liara.yaml` ایجاد کند
- trigger رویداد `push` را برای branch مدنظر، مانند `main`، تنظیم کند
- در workflow ابتدا repository checkout و NodeJS راه‌اندازی شود
- Liara CLI با دستوری مانند `npm i -g @liara/cli@9` نصب شود
- استقرار با `liara deploy --app="APP_NAME" --api-token="$LIARA_TOKEN" --no-app-logs` انجام شود
- مقدار `APP_NAME` با شناسه واقعی برنامه جایگزین شود
- Secret با نام دقیق `LIARA_API_TOKEN` در GitHub Actions ساخته و مقدار API Token لیارا در آن قرار گیرد
- در صورت نیاز، پورت برنامه با پارامتر `--port=3000` و شناسه تیم با `--team-id="your-team-id"` به دستور deploy اضافه شود

**expected_sources:**

- [https://docs.liara.ir/paas/cicd/github/](https://docs.liara.ir/paas/cicd/github/)

**expected_clarification:** none

**expected_abstention:** false

**difficulty:** hard

**tags:** service=paas, runtime=any, framework=github-actions

**notes:** Token نباید داخل فایل workflow هاردکد شود؛ پاسخ باید ساختار workflow و محل Secret را جداگانه توضیح دهد

---

## Q5

**question:** یه پروژه TypeScript با Prisma و PostgreSQL دارم. برای migration و deploy امنش روی NodeJS لیارا چه مراحلی لازمه؟

**expected_answer_points:**

- Prisma برای PostgreSQL با `npx prisma init --datasource-provider postgresql` راه‌اندازی شود
- متغیر `DATABASE_URL` با URI دیتابیس PostgreSQL مقداردهی شود
- migration اولیه پیش از استقرار با `npx prisma migrate dev --name init` ساخته شود
- اسکریپت build شامل `npx prisma generate && tsc` باشد
- اسکریپت start برنامه خروجی buildشده را اجرا کند، مانند `node dist/src/server.js`
- فایل `liara_pre_start.sh` ایجاد و دستور `npx prisma migrate deploy` در آن قرار گیرد
- `DATABASE_URL` در متغیرهای محیطی برنامه لیارا ثبت شود
- برنامه و دیتابیس PostgreSQL لیارا ترجیحاً در یک شبکه خصوصی مشترک باشند و از URI شبکه خصوصی استفاده شود
- برنامه با پورتی هماهنگ با کد مستقر شود، مانند `liara deploy --port 3000`

**expected_sources:**

- [https://docs.liara.ir/paas/nodejs/how-tos/connect-to-db/prisma/](https://docs.liara.ir/paas/nodejs/how-tos/connect-to-db/prisma/)
- [https://docs.liara.ir/paas/details/envs/](https://docs.liara.ir/paas/details/envs/)
- [https://docs.liara.ir/paas/details/private-network/](https://docs.liara.ir/paas/details/private-network/)

**expected_clarification:** none

**expected_abstention:** false

**difficulty:** hard

**tags:** service=paas, runtime=nodejs, framework=prisma

**notes:** پاسخ باید ترتیب توسعه، migration، pre-start و deploy را حفظ کند و از نمایش credential واقعی خودداری کند

---

## Q6

**question:** Flask رو deploy کردم ولی توی لاگ می‌بینم `ModuleNotFoundError: No module named 'app'`. چطور درستش کنم؟

**expected_answer_points:**

- لیارا برنامه Flask را به‌طور پیش‌فرض مشابه `gunicorn app:app` اجرا می‌کند
- به همین دلیل نام ماژول اصلی به‌صورت پیش‌فرض `app` فرض می‌شود
- یک راه، تغییر نام ماژول اصلی برنامه به `app` است
- راه دیگر، ساخت فایل `liara.json` در ریشه پروژه و تنظیم `flask.appModule` با مقدار `<module-name>:app` است
- پس از جایگزین کردن نام واقعی ماژول، برنامه دوباره مستقر شود

**expected_sources:**

- [https://docs.liara.ir/paas/flask/fix-common-errors/module-not-found/](https://docs.liara.ir/paas/flask/fix-common-errors/module-not-found/)

**expected_clarification:** none

**expected_abstention:** false

**difficulty:** medium

**tags:** service=paas, runtime=python, framework=flask

**notes:** متن خطا و کلید `flask.appModule` باید دقیق باقی بمانند

---

## Q7

**question:** deploy برنامه‌ی .NET موفقه ولی سایت `502 Bad Gateway` می‌ده؛ داخل کد URL رو روی `http://localhost:5000` گذاشتم.

**expected_answer_points:**

- استفاده از `localhost` باعث می‌شود gateway به برنامه دسترسی نداشته باشد
- host باید از `localhost` به `0.0.0.0` تغییر کند
- در `Program.cs` می‌توان از `.UseUrls("http://0.0.0.0:5000")` استفاده کرد
- پورت deploy باید با پورت برنامه یکی باشد
- برای این مثال استقرار با `liara deploy --port 5000` انجام شود

**expected_sources:**

- [https://docs.liara.ir/paas/dotnet/fix-common-errors/502-bad-gateway/](https://docs.liara.ir/paas/dotnet/fix-common-errors/502-bad-gateway/)

**expected_clarification:** none

**expected_abstention:** false

**difficulty:** medium

**tags:** service=paas, runtime=dotnet, framework=aspnet-core

**notes:** پاسخ نباید 502 را به‌صورت کلی عیب‌یابی کند؛ سرنخ `localhost:5000` علت مورد انتظار را مشخص کرده است

---

## Q8

**question:** برنامه‌ام باید روی لیارا فایل بنویسه؛ کجا ذخیره‌ش کنم؟

**expected_answer_points:**

- پیش از پیشنهاد مسیر، مشخص کند موقتی یا ماندگار بودن فایل تعیین‌کننده راه‌حل است
- اگر فایل موقتی باشد، `/tmp` با فضای پیش‌فرض ۱۰۰ مگابایت قابل استفاده است
- writable کردن فایل‌سیستم فقط تغییرات موقتی می‌دهد و داده ممکن است پس از توقف، restart یا deploy مجدد از بین برود
- اگر فایل باید ماندگار باشد، باید دیسک ساخته شود
- دیسک باید در مرحله استقرار به یک دایرکتوری مشخص mount شود و امکان mount روی ریشه `/` وجود ندارد

**expected_sources:**

- [https://docs.liara.ir/paas/details/file-system/](https://docs.liara.ir/paas/details/file-system/)
- [https://docs.liara.ir/paas/disks/create/](https://docs.liara.ir/paas/disks/create/)
- [https://docs.liara.ir/paas/disks/route/](https://docs.liara.ir/paas/disks/route/)

**expected_clarification:** فایل‌ها موقتی‌اند یا باید بعد از restart و deploy مجدد باقی بمانند؟

**expected_abstention:** false

**difficulty:** medium

**tags:** service=paas, runtime=any, framework=any

**notes:** سؤال تکمیلی load-bearing است؛ پاسخ برای فایل موقتی و ماندگار متفاوت است

---

## Q9

**question:** برای وصل شدن به PostgreSQL لیارا باید از کدوم URI استفاده کنم؟

**expected_answer_points:**

- پیش از انتخاب URI مشخص کند کلاینت داخل لیارا و در شبکه خصوصی مشترک است یا از لوکال/بیرون لیارا وصل می‌شود
- برای برنامه داخل لیارا، برنامه و دیتابیس بهتر است در شبکه خصوصی مشترک باشند و URI شبکه خصوصی استفاده شود
- برای لوکال یا هر کلاینت خارج از لیارا باید دسترسی شبکه عمومی دیتابیس فعال باشد و اطلاعات یا URI شبکه عمومی استفاده شود
- URI مناسب از صفحه نحوه اتصال دیتابیس برداشته شود
- اگر دسترسی عمومی خاموش باشد، لینک‌های شبکه عمومی نمایش داده نمی‌شوند و قابل استفاده نیستند

**expected_sources:**

- [https://docs.liara.ir/dbaas/postgresql/quick-setup/](https://docs.liara.ir/dbaas/postgresql/quick-setup/)
- [https://docs.liara.ir/dbaas/details/connection-links/](https://docs.liara.ir/dbaas/details/connection-links/)
- [https://docs.liara.ir/paas/details/private-network/](https://docs.liara.ir/paas/details/private-network/)

**expected_clarification:** برنامه یا ابزار شما داخل لیارا و در شبکه خصوصی مشترک با دیتابیس اجرا می‌شود، یا از لوکال/بیرون لیارا وصل می‌شوید؟

**expected_abstention:** false

**difficulty:** medium

**tags:** service=dbaas, runtime=any, framework=postgresql

**notes:** سؤال تکمیلی ضروری است؛ انتخاب اشتباه میان URI خصوصی و عمومی اتصال را ناممکن یا ناامن می‌کند

---

## Q10

**question:** لیارا برای ارتباط دو برنامه در شبکه خصوصی دقیقاً چه latency تضمین‌شده‌ای در `p95` و `p99` ارائه می‌دهد؟

**expected_answer_points:**

- مستندات عمومی می‌گویند شبکه خصوصی ارتباط سریع‌تر و امن‌تری فراهم می‌کند
- مستندات عمومی عدد تضمین‌شده‌ای برای latency در `p95` یا `p99` ارائه نمی‌کنند
- از ساختن عدد، بازه یا تضمین عملکرد خودداری کند
- برای عدد تضمین‌شده پیشنهاد کند از پشتیبانی لیارا استعلام شود؛ برای وضعیت واقعی workload نیز benchmark انجام شود

**expected_sources:**

- [https://docs.liara.ir/paas/details/private-network/](https://docs.liara.ir/paas/details/private-network/)

**expected_clarification:** none

**expected_abstention:** true

**difficulty:** hard

**tags:** service=paas, runtime=any, framework=any

**notes:** abstention باید نسبت به عدد تضمین‌شده باشد؛ پاسخ می‌تواند تنها ادعای کیفی موجود در منبع را بیان کند و نباید latency فرضی بسازد
