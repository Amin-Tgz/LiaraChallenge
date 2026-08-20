# Liara Documentation Rescue Assistant

> سند مرجع محصول، معماری و برنامه‌ی پیاده‌سازی برای مسابقه‌ی لیارا

## 1. وضعیت سند

- **نام کاری پروژه:** Liara Documentation Rescue Assistant
- **وضعیت:** OpenSpec change ساخته شد — `openspec/changes/add-docs-rescue-assistant/`
- **مالک و مجری:** یک توسعه‌دهنده
- **زمان پیاده‌سازی:** **حداکثر دو روز** (قطعی)
- **زبان اصلی محصول:** فارسی، با پشتیبانی صحیح از محتوای فنی انگلیسی و کدهای LTR
- **زیرساخت مقصد:** لیارا
- **منبع داده:** فقط مستندات عمومی لیارا
- **مخزن مستندات:** `https://github.com/liara-cloud/docs`
- **وب‌سایت مستندات:** `https://docs.liara.ir/`

### قلمرو این سند و ترتیب اولویت

این سند مالک **دامنه‌ی محصول** است: مسئله، کاربران، تجربه‌ی کاربری، معیارهای داوری، سناریوی دمو و Definition of Done.

`docs/deployment.md` مالک **زیرساخت و پیکربندی** است: سرویس‌ها، مدل‌ها، قیمت، متغیرهای محیطی، pre-pass مربوط به MDX، taxonomy خطاها و ترتیب استقرار. آن سند دیرتر و بر پایه‌ی واقعیت‌های تأییدشده نوشته شده است.

```text
openspec/changes/<active>/  →  docs/deployment.md  →  این سند
   (مشخص‌ترین)                    (زیرساخت)            (دامنه‌ی محصول)
```

در تعارض زیرساختی، `deployment.md` مقدم است. در تعارض مربوط به دامنه‌ی محصول، این سند مقدم است. اگر در زمان پیاده‌سازی تصمیمی با این‌ها تعارض داشت، ابتدا سند یا OpenSpec artifacts به‌روزرسانی شوند و سپس کد تغییر کند.

> **نکته:** بخش‌های ۸ (معماری)، ۹.۳ و ۹.۴ (زیرساخت و AI)، ۱۰ (هزینه) و ۲۱ (Observability) در `deployment.md` با جزئیات دقیق‌تر و مقادیر تأییدشده بازنویسی شده‌اند. مقادیر عملیاتی را از آنجا بخوانید.

---

## 2. مسئله

کاربران لیارا گاهی پاسخ سؤال خود را در مستندات پیدا نمی‌کنند؛ دلایل احتمالی:

- نمی‌دانند سؤال به کدام سرویس، runtime یا framework مربوط است.
- عبارت مورد جست‌وجوی آن‌ها با واژگان مستندات متفاوت است.
- سؤال مبهم یا چندمرحله‌ای است.
- پاسخ میان چند صفحه پراکنده است.
- پاسخ به screenshot یا تصویر پنل وابسته است.
- کاربر با Coding Agent کار می‌کند و ترجیح می‌دهد Agent مستقیماً مستندات را بخواند.
- پاسخ موردنیاز واقعاً در مستندات وجود ندارد.

یک chatbot ساده همیشه بهترین پاسخ نیست؛ زیرا هزینه‌ی inference دارد و ممکن است پاسخ ساختگی تولید کند. محصول باید کاربر را ابتدا به ارزان‌ترین مسیر قابل‌اعتماد هدایت کند و فقط هنگام نیاز از Chat/Agent استفاده کند.

---

## 3. ایده و ارزش پیشنهادی

محصول یک «سیستم نجات کاربر از بن‌بست مستندات» است، نه صرفاً یک chatbot.

کاربر سؤال خود را فقط یک‌بار وارد می‌کند و سامانه به‌ترتیب این مسیرها را در اختیار او قرار می‌دهد:

1. نمایش پرسش‌ها و پاسخ‌های مرتبط (FAQ semantic search).
2. اگر پاسخ پیدا نشد، نمایش ابزارهای نجات:
   - **بیل:** Skill قابل‌نصب برای Coding Agent.
   - **جرثقیل:** MCP متصل به مستندات زنده‌ی لیارا.
   - **هلیکوپتر:** Chat مبتنی بر bounded Agentic RAG.
3. حفظ سؤال و state هنگام جابه‌جایی بین مسیرها.
4. ارائه‌ی پاسخ مستند، مرحله‌ای و دارای citation.
5. تبدیل failureهای واقعی کاربران به داده‌ای برای تشخیص شکاف مستندات.

ارزش برای لیارا:

- کاهش سؤال‌ها و ticketهای تکراری.
- کاهش هزینه‌ی inference با FAQ، Skill و MCP.
- کشف صفحات ناقص، مبهم یا قدیمی.
- مشاهده‌ی failureها و سؤال‌های بدون پاسخ.
- ارائه‌ی تجربه‌ی سازگار با نسل جدید AI Coding Agents.

---

## 4. معیارهای داوری و اولویت اجرایی

مجموع ۳۰۰ امتیاز. تخصیص تلاش باید از تخصیص امتیاز پیروی کند، نه برعکس.

| معیار | امتیاز | سهم | لایه‌ی عمق (بخش ۷) |
| --- | ---: | ---: | --- |
| کیفیت و صحت پاسخ‌ها | 80 | ٪۲۷ | **لایه‌ی A** — بیشترین تمرکز |
| UI و تجربه کاربری | 55 | ٪۱۸ | **لایه‌ی A** |
| Agentic و Personalization | 50 | ٪۱۷ | لایه‌ی B |
| امنیت، پایداری و Monitoring | 50 | ٪۱۷ | لایه‌ی B |
| استقرار روی لیارا | 40 | ٪۱۳ | لایه‌ی B — ولی **اول** انجام می‌شود |
| بهینه‌سازی هزینه | 25 | ٪۸ | لایه‌ی C |

قاعده‌ی مدیریت زمان:

> هیچ ابزار زیرساختی یا قابلیت جانبی نباید باعث ناقص‌ماندن کیفیت پاسخ، UX اصلی، MCP، Skill یا استقرار روی لیارا شود.

پس از افزایش هدف ظرفیت به ۳۰۰ کاربر هم‌زمان، OpenTelemetry، Prometheus، Grafana، Loki و Alloy به دامنه‌ی استقرار اضافه شدند. این سرویس‌ها باید خارج از مسیر درخواست کاربر بمانند؛ اختلال telemetry نباید کیفیت پاسخ یا دسترس‌پذیری مسیر اصلی را کاهش دهد. Dozzle و Lazydocker همچنان خارج از دامنه‌اند.

در معیار ۲۵ امتیازی هزینه هم، آنچه امتیاز می‌آورد **روایت** است: مسیر سریع FAQ، هدایت به Skill و MCP پیش از Chat، cache و ثبت token/cost. کل هزینه‌ی پروژه زیر ۲۰ دلار است، پس خودِ پول موضوع نیست.

---

## 5. کاربران هدف

### 5.1 توسعه‌دهنده‌ی تازه‌وارد لیارا

- نمی‌داند پاسخ در کدام قسمت مستندات است.
- احتمالاً اصطلاح دقیق لیارا را نمی‌داند.
- به پاسخ مرحله‌ای و مثال نیاز دارد.

### 5.2 توسعه‌دهنده‌ی باتجربه با سؤال فنی

- متن خطا، command یا مسئله‌ی چندمرحله‌ای دارد.
- پاسخ دقیق، کوتاه، دارای منبع و قابل‌اجرا می‌خواهد.

### 5.3 کاربر Coding Agent

- با Claude Code، Codex، Cursor یا ابزار مشابه کار می‌کند.
- ترجیح می‌دهد Agent از Skill یا MCP استفاده کند.

### 5.4 تیم پشتیبانی و مستندات لیارا

- به analytics سؤال‌های حل‌شده و حل‌نشده نیاز دارد.
- می‌خواهد شکاف‌های مستندات و هزینه‌ی سیستم را ببیند.

---

## 6. تجربه‌ی اصلی کاربر

### 6.1 صفحه‌ی ورود

- نمایش یک GIF/animation پیکسلی از آهویی که در برف گیر کرده است.
- پیام اصلی با مفهوم زیر:

  > چیزی را که می‌خواستی در مستندات پیدا نکردی؟ سؤالت را اینجا بپرس.

- یک input واضح، قابل‌دسترسی و مناسب سؤال‌های چندخطی.
- سؤال کاربر بلافاصله در یک Conversation پایدار ذخیره شود.

### 6.2 مرحله‌ی پرسش‌های مرتبط

- سؤال کاربر embedding شود.
- سؤال با مجموعه‌ی FAQ/Related Questions مقایسه شود.
- چند سؤال مرتبط همراه جواب کوتاه و لینک منبع نمایش داده شوند.
- ترتیب نتایج در ابتدا بر اساس semantic relevance و curated priority باشد.
- تا زمانی که داده‌ی واقعی نداریم، عنوان UI باید «پرسش‌های مرتبط» باشد، نه «پرسش‌های متداول».
- بعداً popularity از رفتار واقعی کاربران یاد گرفته شود.

### 6.3 اعلام حل‌شدن یا حل‌نشدن

هر پاسخ مرتبط باید این feedback را داشته باشد:

- «پاسخم را گرفتم»
- «هنوز جوابم را پیدا نکردم»

Feedback باید برای analytics و بهبود ranking ذخیره شود.

### 6.4 ابزارهای نجات

پس از انتخاب «هنوز جوابم را پیدا نکردم»، GIF/animation دوم نمایش داده شود و سه گزینه‌ی بصری ارائه شوند:

| نماد | مسیر | توضیح |
| --- | --- | --- |
| بیل | Skill | راهنمای قابل‌نصب برای Agent کاربر |
| جرثقیل | MCP | اتصال زنده‌ی Agent به مستندات لیارا |
| هلیکوپتر | Chat | کمک مستقیم داخل وب‌اپ |

متن فنی «آیا با Agent کار می‌کنی؟» در UI به زبان ساده بیان شود:

- «می‌خواهم داخل ابزارهایی مثل Claude Code، Cursor یا Codex کمک بگیرم.»
- «می‌خواهم همین‌جا پاسخ بگیرم.»

کاربر بتواند بدون نوشتن مجدد سؤال، بین Skill، MCP و Chat جابه‌جا شود و به مرحله‌ی قبل بازگردد.

### 6.5 Chat

- سؤال اولیه به‌صورت خودکار وارد Chat شود.
- Conversation history بعد از refresh و بازکردن مجدد تب باقی بماند.
- پاسخ streaming باشد.
- Markdown، code block، syntax highlighting و لینک‌ها صحیح نمایش داده شوند.
- هر code block دکمه‌ی Copy داشته باشد.
- منابع با عنوان صفحه، section، لینک و نسخه‌ی مستندات نمایش داده شوند.
- اگر chunk دارای تصویر است، تصویر مرتبط در کنار همان مرحله یا citation نمایش داده شود.
- وضعیت‌های `queued`، `retrieving`، `generating`، `retrying`، `completed` و `failed` در UI قابل‌فهم باشند.

---

## 7. دامنه‌ی نسخه‌ی مسابقه

**قاعده‌ی حاکم بر دو روز:** هیچ قابلیتی حذف نمی‌شود؛ فقط **عمق** آن تغییر می‌کند. همه‌ی قابلیت‌ها در دمو حاضرند، ولی بعضی نازک پیاده‌سازی می‌شوند. این باعث می‌شود کم‌کردن دامنه یک تصمیم آگاهانه باشد، نه یک غافلگیری در ساعت آخر.

### 7.1 لایه‌ی A — باید واقعاً باکیفیت باشد

مستقیماً معیارهای ۸۰ و ۵۵ امتیازی را هدف می‌گیرد.

- ingestion و chunking مبتنی بر `<Section>` با anchor دقیق برای citation.
- hybrid retrieval (dense + lexical) با fusion از نوع RRF.
- نرمال‌سازی فارسی، یکسان در زمان ایندکس و زمان کوئری.
- FAQ semantic search عملیاتی.
- Chat RAG دارای citation دقیق و قابل‌کلیک.
- حفظ Conversation و سؤال اولیه بعد از refresh.
- rescue flow کامل: landing → پرسش‌های مرتبط → feedback → سه ابزار نجات.
- RTL صفحه با code blocks به‌صورت LTR و متن ترکیبی فارسی/انگلیسی صحیح.
- تصاویر مرتبط در ingestion، retrieval metadata و UI.

### 7.2 لایه‌ی B — باید موجود و قابل‌نمایش باشد، نازک کافی است

معیارهای ۵۰ و ۴۰ امتیازی.

- bounded Agentic RAG با سقف tool call و rewrite.
- سؤال تکمیلی فقط وقتی پاسخ را عوض می‌کند.
- session technical profile.
- Skill قابل‌نصب و قابل‌استفاده.
- MCP قابل‌نصب و قابل‌استفاده — **اولویت آخر در ترتیب اجرا**، چون به API مستقرشده وابسته است.
- پنل ادمین: احراز هویت، مدیریت FAQ، threshold، دکمه‌ی sync.
- داشبورد سبک quality/cost/failure.
- Portkey gateway به‌عنوان یک app service روی لیارا، با retry، fallback و circuit breaking.
- Rate limiting، token budget و secret management.
- health/readiness تفکیک‌شده و taxonomy خطاها.
- استقرار روی لیارا — **در ساعت اول، نه روز آخر**.

### 7.3 لایه‌ی C — حداقلی

معیار ۲۵ امتیازی و بیمه‌ی کیفیت.

- Opik tracing (hosted) برای spanهای retrieval و LLM.
- structured logging با correlation IDs.
- ثبت token/cost برای هر request.
- exact-match cache.
- evaluation: ۱۰ سؤال golden دست‌نویس + مجموعه‌ی تولیدشده با داور LLM.
- یک مسیر happy path در Playwright.
- `ci.yml` و `deploy.yml`.
- reindex workflow به‌صورت دستی (`workflow_dispatch`).

### 7.4 قابلیت‌های P1 در صورت باقی‌ماندن زمان

- Vision fallback برای تصاویر با alt ضعیف — مدل chat به‌صورت بومی vision دارد، پس هزینه‌ی افزوده‌ی آن صفر است و فقط یک prompt variant لازم دارد.
- توسعه‌ی dashboardهای Grafana فراتر از dashboard و alertهای عملیاتی پایه.
- semantic cache پیشرفته.
- پیشنهاد خودکار draft برای اصلاح مستندات.
- سناریوهای failure در Playwright.
- visual regression گسترده.
- `pg_trgm` برای تطبیق فازی فارسی، در صورت در دسترس بودن روی لیارا.

### 7.5 خارج از Scope مسابقه

- Dozzle و Lazydocker — ابزارهای دستی توسعه‌دهنده‌اند، نه monitoring production.
- اجرای Opik توسط خودمان — استک آن به ClickHouse، MySQL، MinIO و چند سرویس دیگر نیاز دارد.
- اجرای embedding روی سخت‌افزار خودمان در production.
- Kubernetes.
- احراز هویت کاربران نهایی — فقط ادمین.
- Agent آزاد و نامحدود.
- caption کردن همه‌ی تصاویر با Vision.
- چند Vector Database هم‌زمان.
- پنل مدیریت enterprise.
- auto-merge تغییرات مستندات بدون تأیید انسان.
- endpoint نوع `/v1/batch` برای تولید FAQ.

---

## 8. معماری سطح بالا

> توپولوژی دقیق همراه با اندازه‌ی RAM هر سرویس در `docs/deployment.md` §۳ است.

```mermaid
flowchart TD
    U[Browser] --> API["API (FastAPI) + Web bundle<br/>same origin"]
    API --> PG[(PostgreSQL + pgvector)]
    API --> R[(Redis)]
    API --> PK[Portkey Gateway - Liara service]
    W[Worker] --> PG
    W --> R
    W --> PK
    R -.->|"token relay via Redis Streams"| API
    PK --> A[AvalAI Primary]
    PK --> B[OpenAI-compatible Fallback]
    API --> O[Opik SaaS - external]
    W --> O
```

### 8.1 سرویس‌های deployشده

**پنج سرویس، مجموعاً حدود ۵ گیگابایت.**

1. **API + Web:** FastAPI که REST/SSE، FAQ، Chat و MCP endpoint را ارائه می‌دهد و build نهایی React را هم به‌صورت static سرو می‌کند.
2. **Worker:** indexing، تولید FAQ و jobهای asynchronous.
3. **PostgreSQL + pgvector:** state، metadata، FAQ، chunks و vectors.
4. **Redis:** queue، locks، rate limiting، cache و relay مربوط به streaming.
5. **Portkey Gateway:** provider routing و resiliency.

**چرا Web داخل API ادغام شد؟** اگر Web و API روی دو زیردامنه‌ی جدا باشند، cookie نیازمند `SameSite=None; Secure` و CORS با credentials می‌شود که با قاعده‌ی «CORS محدود» در تضاد است. هم‌ریشه‌بودن هر دو مشکل را هم‌زمان حل می‌کند و یک سرویس هم کم می‌کند.

MCP برای کاهش تعداد سرویس‌ها در همان API ارائه می‌شود.

### 8.2 دو محیط اجرا

هیچ سرویسی «self-host» نیست؛ دقیقاً دو محیط وجود دارد و هر سرویس در هر دو حاضر است.

| | توسعه‌ی محلی | production |
| --- | --- | --- |
| اجرا | Docker Desktop و `docker compose` | سرویس‌های لیارا |
| PostgreSQL + pgvector | container | PostgreSQL مدیریت‌شده‌ی لیارا با افزونه‌ی Pgvector |
| Redis | container | Redis مدیریت‌شده‌ی لیارا |
| API + Web | container با hot reload | app service لیارا |
| Worker | container | app service لیارا |
| Portkey Gateway | container | app service لیارا از همان image |
| پیکربندی | فایل `.env` در gitignore | پنل secrets لیارا |

**Portkey در هر دو محیط image خودمان است** — نسخه‌ی open-source gateway را اجرا می‌کنیم، نه سرویس SaaS شرکت Portkey.

**Opik تنها وابستگی خارجی است.** چیزی از آن deploy نمی‌شود و هر دو محیط به همان endpoint ابری وصل می‌شوند. اجرای خودمان از Opik خارج از Scope است چون به ClickHouse، MySQL، MinIO و چند سرویس دیگر نیاز دارد.

`docker-compose.yml` باید کل استک را با یک دستور بالا بیاورد تا فاصله‌ی محیط توسعه و production کم بماند و همان imageها روی لیارا بروند.

---

## 9. پشته‌ی فنی

### 9.1 Backend

- Python
- FastAPI
- Pydantic Settings
- SQLAlchemy 2.x یا SQLModel با migration از طریق Alembic
- `uv` برای dependency management
- `pyproject.toml` و `uv.lock`
- Ruff برای lint و format
- Pytest برای unit/integration tests

قواعد dependency:

- `uv.lock` باید commit شود.
- CI و Docker باید از `uv sync --frozen` استفاده کنند.
- نسخه‌ی Python در `.python-version` و `requires-python` مشخص شود.

### 9.2 Frontend

- React
- TypeScript strict
- Vite
- shadcn/ui
- Tailwind CSS
- React Router یا router سبک معادل
- TanStack Query برای server state
- Markdown renderer با syntax highlighting
- Playwright برای E2E

راهنمای طراحی:

- Skill رسمی shadcn/ui برای component implementation.
- UI/UX Pro Max برای design system و UX review.
- RTL، accessibility و code blocks LTR باید مستقل و صریح تست شوند؛ به Skillهای طراحی اعتماد کامل نشود.

### 9.3 داده و زیرساخت

- PostgreSQL
- pgvector
- Redis
- Docker و Docker Compose
- GitHub Actions
- Liara deployment

### 9.4 AI

> فهرست کامل و به‌روز متغیرهای محیطی در `docs/deployment.md` §۵ است. خلاصه‌ی زیر فقط تصمیم‌های محصولی را نگه می‌دارد.

- Provider API باید OpenAI-compatible باشد.
- Primary provider: AvalAI.
- Secondary provider: یک provider دیگر OpenAI-compatible (گزینه‌ها: Vercel AI Gateway یا GapGPT).
- Gateway: Portkey — image خودمان، در توسعه با docker compose و در production به‌عنوان app service لیارا.
- مدل Chat و FAQ: `gemini-3.7-flash` — از environment تنظیم شود و hard-code نشود.
- مدل embedding قطعی: `text-embedding-3-large`.
- **ابعاد embedding قطعی: `1536`** — نه مقدار پیش‌فرض مدل.
- تنظیمات Chat و Embedding کاملاً جدا باشند.
- مدل داور evaluation باید با مدل تحت آزمون **متفاوت** باشد.

```env
LLM_MODEL=gemini-3.7-flash
FAQ_LLM_MODEL=gemini-3.7-flash
EMBEDDING_MODEL=text-embedding-3-large
EMBEDDING_DIMENSIONS=1536
EVAL_JUDGE_MODEL=<must differ from LLM_MODEL>
```

> **چرا ۱۵۳۶ و نه ۳۰۷۲؟** pgvector سقف ایندکس HNSW را روی ۲۰۰۰ بُعد می‌گذارد، بنابراین مقدار پیش‌فرض مدل (۳۰۷۲) اصلاً قابل ایندکس‌شدن نیست و هر کوئری به sequential scan تبدیل می‌شود. پشتیبانی AvalAI از پارامتر `dimensions` با فراخوانی واقعی تأیید شده است. تصمیم قطعی است؛ تغییر آن کل بردارهای ذخیره‌شده را باطل می‌کند.

بُعد واقعی استفاده‌شده باید در metadata مربوط به index version ثبت شود.

---

## 10. داده‌های مستندات و هزینه‌ی embedding

بررسی اولیه‌ی مخزن فعلی:

- حدود 1,142 فایل MDX در ۱۲ بخش سطح بالا.
- حدود 7.75 MB محتوای MDX.
- حدود 2,512,904 توکن پیش از پاک‌سازی؛ حدود ۱.۸ میلیون توکن پس از حذف JSX.
- نرخ تأییدشده‌ی AvalAI برای `text-embedding-3-large`: **۰.۱۳ دلار به ازای هر یک میلیون توکن**.

> جدول کامل هزینه در `docs/deployment.md` §۸ است. خلاصه: **حدود ۴.۲۵ دلار** برای کل ایندکس اولیه شامل تولید FAQ، و حدود **۰.۰۰۵ دلار برای هر کوئری**. کل هزینه‌ی پروژه زیر ۲۰ دلار می‌ماند.

نتیجه:

- GPU شخصی در معماری production نقشی ندارد.
- embedding از API انجام می‌شود.
- local embedding فقط گزینه‌ی توسعه/آزمایش آینده است.
- **هزینه محدودیت واقعی نیست؛ محدودیت واقعی wall-clock است.** تولید FAQ برای کل مستندات حدود ۸ تا ۱۵ دقیقه طول می‌کشد و embedding یک تا دو دقیقه.

---

## 11. Ingestion Pipeline

### 11.1 مراحل

1. دریافت repository و ثبت source commit SHA.
2. شناسایی فایل‌های افزوده، تغییرکرده و حذف‌شده.
3. parse کردن MDX و حذف importها و اجزای purely presentational.
4. استخراج title، description، heading hierarchy، links، code blocks و images.
5. chunking مبتنی بر section و semantic boundaries.
6. افزودن image alt و surrounding context به متن قابل‌embedding.
7. استخراج deterministic metadata.
8. تولید embedding به‌صورت batch.
9. ساخت index version جدید.
10. اجرای smoke tests و index validation.
11. atomic activation نسخه‌ی جدید.
12. حفظ حداقل یک نسخه‌ی سالم قبلی برای rollback.

### 11.2 قواعد Chunking

> ⚠️ **یافته‌ی مهم از بررسی مخزن واقعی:** عنوان‌های section در این مستندات **Markdown نیستند**. آن‌ها کامپوننت JSX به شکل `<Section id="..." title="..." />` هستند و فقط H1 به‌صورت Markdown نوشته شده است. اگر chunking فقط دنبال heading مارک‌داون بگردد، هر فایل به یک بلوک بزرگ و بی‌ساختار تبدیل می‌شود و کیفیت retrieval بی‌صدا از بین می‌رود.
>
> نکته‌ی مثبت اینکه `id` و `title` صریح هستند، پس `heading_anchor` و `section` بدون حدس‌زدن به‌دست می‌آیند و citation به‌صورت `{source_url}#{id}` مستقیماً به همان بخش لینک می‌دهد. جدول کامل تبدیل‌ها در `docs/deployment.md` §۷ است.

- مرز اصلی chunk، کامپوننت `<Section>` است؛ H1 مارک‌داون مرز سطح بالاتر.
- تطبیق باید بر اساس **نام تگ JSX** باشد، نه مسیر import — مخزن در مسیرهای import ناسازگار است.
- code block از توضیح بلافاصله قبل و بعد خود جدا نشود.
- Step component و تصویر مرتبط در یک logical chunk باقی بمانند.
- breadcrumb و section title به متن embedding افزوده شوند.
- chunk بیش‌ازحد کوچک یا فاقد معنای مستقل ساخته نشود.
- overlap محدود و configurable باشد.
- لینک source و anchor دقیق برای هر chunk حفظ شود.

### 11.3 Metadata هر Chunk

```json
{
  "chunk_id": "paas-python-flask-envs-03",
  "document_id": "paas-python-flask-envs",
  "title": "استفاده از متغیرهای محیطی",
  "section": "خواندن متغیر محیطی در Flask",
  "breadcrumbs": ["PaaS", "Python", "Flask", "Environment Variables"],
  "service": "paas",
  "runtime": "python",
  "framework": "flask",
  "content_type": "tutorial",
  "language": "fa",
  "code_languages": ["python"],
  "source_path": "src/pages/paas/flask/envs.mdx",
  "source_url": "https://docs.liara.ir/paas/flask/envs",
  "source_commit": "<git-sha>",
  "heading_anchor": "استفاده-از-متغیرهای-محیطی",
  "images": [],
  "indexed_at": "<timestamp>"
}
```

Metadata برای soft boosting استفاده شود. فیلتر سخت فقط زمانی اعمال شود که intent کاربر صریح و قابل‌اعتماد است.

---

## 12. راهبرد تصاویر

بررسی اولیه‌ی مخزن:

- حدود 440 image tag.
- حدود 380 image URL یکتا.
- تقریباً همه‌ی تصاویر alt دارند.
- تصاویر عمدتاً screenshot مراحل پنل، diagram یا GIF هستند.

### 12.1 رفتار پیش‌فرض

- تصویر از chunk مرتبط جدا نشود.
- `alt` و surrounding instructional text وارد متن embedding شوند.
- URL، alt، type و position تصویر در metadata ذخیره شوند.
- تصویر اصلی هنگام پاسخ در Web UI نمایش داده شود.
- MCP تصویر را به‌صورت URL + alt + structured metadata برگرداند.
- Skill به Agent بگوید تصویر مرتبط را در پاسخ حفظ کند.

### 12.2 Vision Fallback

**وضعیت: P1 (بخش ۷.۴).** مدل chat یعنی `gemini-3.7-flash` به‌صورت بومی vision دارد، بنابراین این قابلیت نیازی به مدل جداگانه، متغیر محیطی جداگانه یا یکپارچه‌سازی تازه ندارد و صرفاً یک prompt variant روی همان client است. هزینه‌ی افزوده‌ی آن عملاً صفر است، ولی در دو روز جزو لایه‌ی الزامی نیست.

Vision فقط در این حالت‌ها اجرا شود:

- alt خالی، گنگ یا فاقد اطلاعات است.
- سؤال ماهیت بصری دارد: «کجا کلیک کنم؟»، «این گزینه کجاست؟» و مشابه آن.

Caption تولیدشده:

- بر اساس image hash cache شود.
- فقط برای منابع allowlisted مستندات لیارا تولید شود.
- source commit و image URL را حفظ کند.

caption کردن تمام تصاویر در Scope مسابقه نیست.

---

## 13. Retrieval و FAQ

### 13.1 FAQ/Related Questions Fast Path

- مجموعه‌ی سؤال و جواب‌های مرتبط **با LLM از روی مستندات ایندکس‌شده تولید شود**، سپس در پنل ادمین بازبینی، ویرایش یا حذف شود.
- تولید یک‌بار برای کل مستندات اجرا می‌شود؛ پس از آن ادمین با دکمه‌ی sync فقط برای مستندات جدید یا تغییرکرده دوباره تولید می‌کند.
- خروجی تولید با structured output اعتبارسنجی شود تا خطاهای parse حذف شوند.
- query embedding با embedding سؤال‌های FAQ مقایسه شود — یک فضای embedding جدا از chunkها.
- نتایج بر اساس semantic similarity و curated priority مرتب شوند.
- threshold و top-k configurable باشند و **threshold از پنل ادمین قابل تغییر باشد**.
- واحد آستانه **similarity** است، نه distance. مقدار پیش‌فرض `0.4`.
- نتیجه‌ی ضعیف نباید به‌زور نمایش داده شود؛ در این حالت به کاربر گفته شود چیزی پیدا نشد و ابزارهای نجات پیشنهاد شوند.
- این مسیر باید کاملاً sync باشد و **هیچ فراخوانی مدل برای تولید پاسخ نداشته باشد**.
- success/failure feedback ذخیره شود.

Popularity در آینده از داده‌های واقعی محاسبه شود:

- impression count
- click count
- solved feedback
- unresolved feedback
- انتقال به Skill/MCP/Chat

### 13.2 Document Retrieval

Retrieval باید hybrid باشد:

- dense vector retrieval برای معنا.
- lexical retrieval برای command، service name، error code و عبارات دقیق.
- fusion نتایج با روش شفاف و قابل‌تنظیم مانند RRF.
- evidence selection/reranking پیش از پاسخ نهایی.

خروجی retrieval باید شامل score، متن chunk، metadata، images، source URL و source commit باشد.

---

## 14. Bounded Agentic RAG

Agent آزاد و عمومی ساخته نشود. Agent فقط ابزارهای allowlisted زیر را داشته باشد:

```text
search_docs(query, service?, runtime?, framework?, top_k?)
read_doc(document_id_or_url, section?)
search_related_questions(query, top_k?)
```

MCP می‌تواند ابزار کاربرمحور زیر را نیز ارائه کند:

```text
diagnose_liara_issue(service?, runtime?, framework?, stage?, error_message?)
```

### 14.1 محدودیت‌ها

- حداکثر 3 tool call برای هر turn.
- حداکثر 2 query rewrite.
- token budget مشخص.
- timeout مشخص.
- فقط مستندات allowlisted لیارا.
- citation اجباری برای ادعاهای فنی.
- در نبود evidence کافی، پاسخ ساختگی ممنوع است.

### 14.2 Clarification

Agent فقط در صورت اثرگذاری واقعی سؤال تکمیلی بپرسد؛ نمونه‌ها:

- از کدام سرویس لیارا استفاده می‌کنی؟
- runtime یا framework چیست؟
- خطا هنگام build است یا runtime؟
- متن کامل خطا چیست؟
- از Docker استفاده می‌کنی یا deployment مستقیم؟

### 14.3 پاسخ نهایی

پاسخ باید:

- مستقیم و متناسب با سطح کاربر باشد.
- مراحل قابل‌اجرا ارائه کند.
- code/commands را صحیح قالب‌بندی کند.
- منابع مرتبط را دقیق نشان دهد.
- در صورت نیاز تصویر راهنما نمایش دهد.
- قدم بعدی و روش بررسی موفقیت را پیشنهاد کند.
- عدم اطمینان یا نبود پاسخ را صریح اعلام کند.

---

## 15. Personalization

Personalization نسخه‌ی مسابقه session-based و فنی است، نه پروفایل شخصی دائمی.

```json
{
  "service": "paas",
  "runtime": "python",
  "framework": "fastapi",
  "experience_level": "beginner",
  "current_goal": "deploy",
  "deployment_mode": "docker",
  "known_error": "..."
}
```

این profile از مکالمه به‌روزرسانی شود و برای retrieval boosting، clarification و سطح توضیح استفاده شود.

---

## 16. MCP

MCP نسخه‌ی مسابقه باید واقعاً قابل‌نصب و مستند باشد.

### ابزارهای اجباری

- `search_liara_docs`
- `get_liara_doc`
- `diagnose_liara_issue`

### الزامات

- schema ورودی و خروجی دقیق.
- output شامل citation و image metadata.
- timeout و errorهای قابل‌فهم.
- rate limiting.
- نمونه‌ی config برای Claude Code/Codex/Cursor.
- smoke test با MCP Inspector یا host واقعی.
- عدم نیاز به API key لیارا برای دسترسی به مستندات عمومی، مگر برای حفاظت سرویس MCP خود پروژه.

---

## 17. Skill

Skill باید یک workflow حل مسئله باشد، نه صرفاً لینک مستندات.

Skill به Agent آموزش دهد:

1. intent و سرویس مرتبط را تشخیص دهد.
2. اطلاعات ضروری گم‌شده را از کاربر بپرسد.
3. ابتدا MCP را برای retrieval استفاده کند.
4. پاسخ را فقط بر اساس evidence ارائه دهد.
5. code و commands را قابل‌اجرا نشان دهد.
6. منابع و تصاویر مرتبط را حفظ کند.
7. در نبود evidence حدس نزند.
8. قدم بعدی و verification step پیشنهاد دهد.

Skill باید دارای README نصب، نسخه و تست نمونه باشد.

---

## 18. State، Durability و Queue

### 18.1 State پایدار

State اصلی فقط در React state یا Local Storage نگهداری نشود.

جداول/موجودیت‌های اصلی:

- `sessions`
- `conversations`
- `messages`
- `request_jobs`
- `feedback`
- `faq_items`
- `documents`
- `document_chunks`
- `index_versions`
- `image_assets`
- `usage_events`

کاربر ناشناس یک session ID امن در cookie داشته باشد. Conversation ID برای بازیابی history استفاده شود.

### 18.2 Job Lifecycle

```text
queued -> retrieving -> generating -> completed
queued -> retrieving -> retrying -> completed
queued -> ... -> failed
```

- سؤال قبل از enqueue در PostgreSQL ذخیره شود.
- هر درخواست idempotency key داشته باشد.
- refresh باعث ایجاد job تکراری نشود.
- job بعد از disconnect کاربر ادامه پیدا کند.
- UI پس از بازگشت، history و job status را بازیابی کند.
- SSE برای streaming و reconnect استفاده شود.

### 18.3 Queue

- FAQ search در مسیر sync و سریع باشد.
- Chat/Agent jobها در queue قرار گیرند.
- Redis برای queue/lock/cache استفاده شود.
- job شکست‌خورده پس از retryهای محدود وارد failed/dead-letter state شود.
- timeout و cancellation پشتیبانی شوند.

---

## 19. Provider Resilience

Portkey مسئول این موارد باشد:

- OpenAI-compatible gateway.
- retries با exponential backoff.
- احترام به `Retry-After`.
- provider/model fallback.
- circuit breaker.
- request timeout.
- conditional routing.
- cost/usage visibility در صورت پشتیبانی.

Retry فقط برای failureهای transient مانند timeout، 429 و 5xx انجام شود. validation/auth errors بدون retry fail شوند.

از retry amplification جلوگیری شود:

- retry مربوط به LLM در Gateway انجام شود.
- Worker فقط برای failure زیرساختی job retry محدود داشته باشد.

---

## 20. امنیت و کنترل هزینه

### 20.1 امنیت

- API keyها فقط در Liara Secrets/Environment Variables.
- هیچ secret در frontend یا repository قرار نگیرد.
- logs باید secret، cookie و token را redact کنند.
- rate limiting بر اساس IP و session.
- محدودیت طول سؤال و history.
- allowlist ابزارها و دامنه‌های retrieval.
- محتوای مستندات به‌عنوان data و نه instruction پردازش شود.
- prompt injection tests برای retrieved content.
- CORS محدود.
- admin dashboard محافظت شود.
- dependency و container imageها pin شوند.

### 20.2 کنترل هزینه

- FAQ fast path.
- پیشنهاد Skill/MCP قبل از Chat.
- semantic/exact cache برای سؤال‌های پرتکرار.
- token budget و tool-call limit.
- history truncation/summarization کنترل‌شده.
- context فقط از chunkهای relevant.
- embedding incremental.
- ثبت token/cost برای هر request.
- عدم ارسال تصویر به Vision مگر هنگام نیاز واقعی.

---

## 21. Observability

### 21.1 تفکیک مسئولیت

> برای آزمون بار ۳۰۰ کاربر هم‌زمان، telemetry عملیاتی به استقرار اضافه شد؛ اما همچنان خارج از مسیر درخواست است و خرابی آن نباید درخواست rescue را خراب کند.

| ابزار | مسئولیت | وضعیت |
| --- | --- | --- |
| Opik (hosted) | LLM/RAG/Agent tracing، evaluation و cost | داخل Scope |
| structured JSON logging | رویدادهای runtime همراه با correlation IDs | داخل Scope |
| شمارنده‌ها در PostgreSQL | متریک‌های محصولی و داشبورد | داخل Scope |
| OpenTelemetry / Prometheus | ارسال log با OTLP و متریک‌های runtime | داخل Scope |
| Grafana / Loki / Alloy | visualization، alerting، ذخیره و انتقال log | داخل Scope |
| Dozzle / Lazydocker | ابزار دستی توسعه‌دهنده، نه monitoring production | خارج از Scope |

### 21.2 Correlation IDs

تمام اجزا در صورت امکان این شناسه‌ها را حمل کنند:

- `trace_id`
- `session_id`
- `conversation_id`
- `job_id`
- `provider_request_id`
- `index_version`

### 21.3 Metrics اجباری

- request count، latency و error rate.
- queue depth و queue wait time.
- job success/failure/retry.
- provider fallback و circuit state.
- token usage و cost.
- cache hit rate.
- retrieval latency.
- FAQ solved/unresolved rate.
- انتقال FAQ به Skill/MCP/Chat.
- آخرین index commit و index status.
- count سؤال‌های بدون evidence.

### 21.4 Health

- `/health/live`
- `/health/ready`
- Docker health checks.
- graceful shutdown برای Worker/API.

---

## 22. Dashboard سبک مسابقه

داشبورد باید حداقل این موارد را نشان دهد:

- درصد حل‌شدن در FAQ.
- درصد انتخاب Skill، MCP و Chat.
- سؤال‌های پرتکرار حل‌نشده.
- صفحات دارای بیشترین unresolved feedback.
- تعداد و نرخ failureها.
- هزینه و token usage.
- provider fallback count.
- وضعیت آخرین indexing.
- آخرین source commit و index version.

Dashboard پیچیده‌ی enterprise لازم نیست؛ صحت داده و نمایش داستان کاهش هزینه مهم‌تر است.

---

## 23. CI/CD

### 23.1 Workflowهای پروژه

```text
.github/workflows/
  ci.yml
  e2e.yml
  rag-evaluation.yml
  docs-index.yml
  build-images.yml
  deploy.yml
```

### 23.2 CI Pull Request

Backend:

```bash
uv sync --frozen
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

Frontend:

```bash
npm ci
npm run lint
npm run typecheck
npm run test
npm run build
```

UI/E2E:

```bash
npm run test:e2e
```

Playwright artifacts در failure:

- screenshot
- video در صورت فعال‌بودن
- trace archive
- console/network failure summary

### 23.3 Docs Index Workflow

چون پروژه مالک repository مستندات لیارا نیست، workflow باید:

- به‌صورت schedule و workflow_dispatch اجرا شود.
- آخرین commit SHA را با index فعال مقایسه کند.
- در صورت نبود تغییر، بدون هزینه خارج شود.
- فقط فایل‌های تغییرکرده را reindex کند.
- index جدید را قبل از activation validate کند.
- در failure نسخه‌ی قبلی را فعال نگه دارد.
- نتیجه را log و metric کند.

اگر بعداً webhook رسمی در دسترس بود، trigger webhook نیز اضافه شود.

### 23.4 Deployment

- فقط بعد از موفقیت CI.
- build imageهای immutable و versioned.
- migration کنترل‌شده.
- health/readiness check پس از deploy.
- rollback در failure.

---

## 24. قوانین Agentهای کدنویسی در Repository

فایل‌های زیر ایجاد شوند:

```text
AGENTS.md
CLAUDE.md
RULES.md
openspec/config.yaml
```

### 24.1 نقش فایل‌ها

- `AGENTS.md`: دستورهای حیاتی و canonical برای همه‌ی Coding Agentها.
- `CLAUDE.md`: import از `AGENTS.md` و فقط موارد خاص Claude Code.
- `RULES.md`: قواعد کامل معماری، workflow، تست، امنیت و Definition of Done.

نمونه‌ی `CLAUDE.md`:

```md
@AGENTS.md

# Claude Code

Read and follow RULES.md before implementation.
Use OpenSpec artifacts as the source of truth.
```

### 24.2 قواعد اجباری Agent

برای هر task:

1. OpenSpec task و acceptance criteria را بخواند.
2. قبل از تغییر، فایل‌های مرتبط را بررسی کند.
3. فقط Scope لازم را تغییر دهد.
4. test متناسب با تغییر را اضافه/به‌روزرسانی کند.
5. lint، typecheck و tests مرتبط را اجرا کند.
6. برای UI تغییرکرده Playwright اجرا کند.
7. console و network errors را بررسی کند.
8. screenshot/trace را در صورت نیاز بازبینی کند.
9. telemetry و error handling را برای مسیر جدید اضافه کند.
10. task را فقط پس از عبور acceptance criteria کامل علامت بزند.

---

## 25. Test Strategy

### 25.1 Unit Tests

- MDX parsing.
- section-aware chunking.
- metadata extraction.
- image association.
- ranking/fusion.
- citation construction.
- token budget.
- state transitions.
- retry classification.

### 25.2 Integration Tests

- PostgreSQL/pgvector retrieval.
- Redis queue و idempotency.
- Portkey primary/fallback behavior با mock provider.
- failure در telemetry (Opik یا logging) نباید request اصلی کاربر را fail کند.
- index activation و rollback.
- MCP tool schemas و responses.

### 25.3 E2E با Playwright

سناریوی اصلی:

1. ورود به landing.
2. ثبت سؤال.
3. مشاهده‌ی Related Questions.
4. انتخاب unresolved.
5. نمایش سه ابزار نجات.
6. ورود به Chat با حفظ سؤال.
7. دریافت clarification.
8. دریافت پاسخ دارای code/citation/image.
9. refresh صفحه.
10. مشاهده‌ی history و state قبلی.
11. بازگشت و انتخاب MCP یا Skill.

سناریوهای failure:

- provider timeout.
- primary provider failure و fallback موفق.
- تمام providerها unavailable.
- rate limit.
- disconnect و reconnect در streaming.
- سؤال بدون evidence.

### 25.4 Responsive/Accessibility

- mobile و desktop.
- RTL صفحه و LTR code.
- keyboard navigation.
- focus states.
- semantic labels.
- contrast.
- loading/error states.

---

## 26. Evaluation

مجموعه‌ی ارزیابی:

Evaluation دو لایه دارد. لایه‌ی انسانی مرجع اعتماد است و لایه‌ی تولیدشده پوشش می‌دهد.

**لایه‌ی ۱ — Golden Set انسانی، ۱۰ سؤال.** فایل: `docs/eval/golden-set.md`. این‌ها دستی و مستقیماً از روی صفحات واقعی مستندات نوشته شده‌اند و بالاترین درجه‌ی اعتماد را دارند. هر افت در این مجموعه، merge به main را مسدود می‌کند. همچنین معیار کالیبراسیون داور است: اگر داور با قضاوت انسانی روی این مجموعه اختلاف داشت، **داور اشتباه است، نه پاسخ**.

| گروه | سؤال‌ها | تعداد |
| --- | --- | ---: |
| ساده و مستقیم | Q1–Q3 | 3 |
| پیچیده/چندمرحله‌ای | Q4–Q5 | 2 |
| دارای error message | Q6–Q7 | 2 |
| مبهم و نیازمند clarification | Q8–Q9 | 2 |
| بدون پاسخ یا خارج از مستندات | Q10 | 1 |

**لایه‌ی ۲ — مجموعه‌ی تولیدشده، حدود ۲۰ تا ۵۰ سؤال.** با LLM از روی chunkها ساخته می‌شود تا پوشش ارزان در سرویس‌ها و سطوح دشواری مختلف به‌دست آید. سیگنال جهت‌دهنده است، نه دروازه.

> ده سؤال واقعی از شصت سؤال تولیدشده ارزشمندتر است. مهم‌ترین سطر جدول بالا Q10 است: تنها سؤالی که fabrication را آشکار می‌کند.

برای هر سؤال:

- expected answer points.
- expected source pages.
- expected clarification behavior.
- expected abstention behavior.
- difficulty.
- service/runtime/framework tags.

معیارها:

- retrieval Recall@k.
- citation correctness.
- answer relevance.
- answer completeness.
- groundedness/faithfulness.
- hallucination/unsupported claim rate.
- clarification correctness.
- abstention correctness.
- latency.
- token/cost.

**قاعده‌ی داور:** مدل داور (`EVAL_JUDGE_MODEL`) باید با مدل تحت آزمون (`LLM_MODEL`) **متفاوت** باشد. مدلی که خروجی خودش را نمره می‌دهد، سوگیری self-preference دارد؛ ساختار و عبارت‌پردازی خودش را ترجیح می‌دهد و خطاهای خودش را درست می‌شمارد. نتیجه، عددهای دقیق و بی‌معنا است.

`Recall@k` و صحت citation کاملاً **deterministic** محاسبه می‌شوند و هیچ مدلی در آن‌ها دخیل نیست؛ به همین دلیل بیشترین وزن اعتماد روی آن‌هاست. پیش از اعتماد به هر عدد تجمیعی، حدود ۱۰ قضاوت داور روی golden set به‌صورت دستی بازبینی شود.

Evaluation با Opik اجرا و نتیجه‌ی baseline ذخیره شود. تغییر prompt/retrieval مهم نباید بدون مشاهده‌ی regression وارد main شود.

---

## 27. API سطح بالا

نام‌ها می‌توانند در design نهایی اصلاح شوند.

```text
POST   /api/v1/conversations
GET    /api/v1/conversations/{id}
POST   /api/v1/conversations/{id}/messages
GET    /api/v1/conversations/{id}/stream
GET    /api/v1/jobs/{id}
POST   /api/v1/jobs/{id}/cancel

POST   /api/v1/faq/search
POST   /api/v1/feedback

GET    /api/v1/skill
GET    /api/v1/mcp/config
POST   /mcp

GET    /api/v1/admin/analytics
GET    /health/live
GET    /health/ready
GET    /metrics
```

همه‌ی mutation endpointها در صورت مناسب‌بودن idempotency key بپذیرند.

---

## 28. Failure Matrix

| Failure | رفتار مورد انتظار |
| --- | --- |
| Docs sync failure | index فعال قبلی حفظ شود |
| Embedding batch failure | batch retry محدود، index جدید فعال نشود |
| Vector retrieval failure | پاسخ graceful و امکان retry؛ در صورت ممکن FAQ lexical fallback |
| Primary LLM failure | Portkey retry/fallback |
| تمام Providerها unavailable | job و سؤال حفظ شوند؛ پیام قابل‌بازیابی |
| Worker restart | job از persisted state ادامه یا safely retry شود |
| Client disconnect | job ادامه یابد؛ SSE reconnect شود |
| Duplicate submit | idempotency از job تکراری جلوگیری کند |
| Opik/OTel unavailable | request کاربر fail نشود؛ telemetry failure log شود |
| Image unavailable | متن/alt نمایش داده شود و پاسخ اصلی باقی بماند |
| No evidence | Agent abstain کند و منابع عمومی/ticket path پیشنهاد دهد |

---

## 29. برنامه‌ی اجرایی

> ترتیب اجرایی دقیق و قابل‌ردیابی در `openspec/changes/add-docs-rescue-assistant/tasks.md` است. آنچه در ادامه می‌آید نمای کلی دو روز است.

**اصل حاکم بر ترتیب: استقرار در ساعت اول، نه روز آخر.** زنجیره‌ی وابستگی این است:

```text
Skill  ──نیاز دارد به──▶  MCP  ──نیاز دارد به──▶  API مستقرشده  ──نیاز دارد به──▶  index زنده
```

هیچ‌کدام از این‌ها تا وقتی استقرار کار نکند قابل تأیید نیستند. پس walking skeleton در ساعت اول deploy می‌شود، وقتی هنوز ساده است.

### پیش‌نیاز — قبل از شروع روز اول

- rotate کردن کلید API لو رفته.
- فعال‌کردن افزونه‌ی pgvector قبل از وجود داده (فعال‌سازی باعث ریستارت دیتابیس می‌شود).
- provision کردن Postgres، Redis و سه سرویس اپلیکیشن.
- تأیید در دسترس بودن provider دوم **از داخل شبکه‌ی لیارا**، نه فقط از سیستم شخصی.

### روز اول — از استقرار تا پاسخ

1. walking skeleton مستقرشده روی لیارا با `/health/ready` سبز.
2. schema و migration، به‌همراه enum مربوط به taxonomy خطاها.
3. نرمال‌ساز فارسی به‌عنوان یک تابع pure و نسخه‌دار.
4. pre-pass مربوط به JSX و chunking بر اساس `<Section>`.
5. embedding کل مستندات و ساخت index version با فعال‌سازی atomic.
6. hybrid retrieval با fusion از نوع RRF و citation دقیق.
7. bounded agent، صف Redis، worker و relay مربوط به SSE.
8. تولید FAQ برای کل مستندات.

### روز دوم — از پاسخ تا محصول

1. rescue flow کامل در frontend، RTL/LTR و رندر پاسخ.
2. Skill به‌همراه راهنمای نصب.
3. پنل ادمین و داشبورد.
4. Portkey، fallback و Opik.
5. rate limiting، secret و health.
6. MCP — آخرین مورد از نظر اولویت.
7. اجرای evaluation روی golden set و ثبت baseline.
8. Playwright happy path و CI/CD.
9. تمرین و ضبط دمو.

### قاعده‌ی نهایی

- feature جدید اضافه نشود مگر برای رفع blocker.
- اگر روز اول طولانی شد، شیر فشار **دامنه‌ی ingestion** است: `INGEST_SECTIONS` را محدود کنید، ship کنید، بعداً با تغییر config دوباره اجرا کنید. هرگز refactor لازم نیست.
- اگر relay مربوط به SSE از برنامه عقب انداخت، جایگزین از پیش تعیین‌شده تولید in-process است.

---

## 30. سناریوی دموی داوری

سؤال پیشنهادی:

> پروژه‌ی FastAPI من روی سیستم خودم اجرا می‌شود، ولی بعد از deploy روی لیارا بالا نمی‌آید.

⚠️ **قبل از ضبط دمو تأیید شود.** بررسی مخزن واقعی نشان داد `src/pages/paas/` برای `django`، `flask`، `nodejs`، `laravel`، `dotnet` و بقیه پوشه‌ی اختصاصی دارد، ولی **پوشه‌ی مستقلی برای FastAPI ندارد**؛ FastAPI فقط به‌صورت عمومی زیر `paas/python/` پوشش داده شده است.
>
> اگر retrieval برای این سؤال نتیجه‌ی قوی برنگرداند، دمو دقیقاً در بدترین لحظه ضعیف می‌شود. یا پوشش FastAPI در `paas/python/how-tos/` و `related-apps/` تأیید شود، یا سؤال به Django یا Flask تغییر کند که بخش کامل دارند. پوشه‌ی `paas/python/fix-common-errors/` هم دقیقاً برای همین دسته از سؤال‌ها ساخته شده و گزینه‌ی خوبی است.

دمو:

1. کاربر سؤال را در landing وارد می‌کند.
2. Related Questions نمایش داده می‌شوند.
3. کاربر unresolved را انتخاب می‌کند.
4. سه ابزار نجات نمایش داده می‌شوند.
5. کاربر هلیکوپتر Chat را انتخاب می‌کند.
6. Chat سؤال اولیه را بدون تایپ مجدد دارد.
7. Agent می‌پرسد failure در build است یا runtime و متن log چیست.
8. Agent چند retrieval انجام می‌دهد.
9. پاسخ مرحله‌ای، command، citation و تصویر مرتبط نمایش داده می‌شود.
10. کاربر refresh می‌کند و Conversation حفظ می‌شود.
11. همان سؤال با MCP داخل Coding Agent پرسیده می‌شود.
12. داشبورد trace، هزینه، fallback و مسیر حل را نشان می‌دهد.

---

## 31. Definition of Done

پروژه برای تحویل آماده است وقتی:

- مسیر اصلی FAQ -> Rescue Choice -> Chat بدون خطای blocker کار کند.
- MCP و Skill با حداقل یک Agent واقعی تست شده باشند.
- پاسخ‌ها citation دقیق و قابل‌کلیک داشته باشند.
- no-evidence behavior پاسخ ساختگی تولید نکند.
- Conversation بعد از refresh حفظ شود.
- provider fallback در یک تست قابل‌نمایش کار کند.
- rate limiting و secret management فعال باشند.
- Opik حداقل retrieval و LLM spans را نمایش دهد.
- health endpoints و metrics در deployment در دسترس باشند.
- CI سبز باشد.
- Playwright happy path و failureهای اصلی را پاس کند.
- reindex workflow نسخه‌ی جدید را بدون خراب‌کردن index قبلی بسازد.
- پروژه روی زیرساخت لیارا deploy شده باشد.
- README شامل setup، architecture، environment variables، deployment و demo باشد.

---

## 32. ریسک‌ها و کاهش ریسک

| ریسک | کاهش ریسک |
| --- | --- |
| Scope زیاد برای یک هفته | P0/P1/Out-of-Scope و vertical slices محدود |
| کیفیت ضعیف retrieval فارسی | hybrid retrieval، metadata، curated evaluation |
| hallucination | citation اجباری، bounded tools، abstention |
| تفاوت OpenAI-compatible providers | capability tests و Portkey adapter |
| failure هنگام deploy | health check، rollback و persisted jobs |
| UI جذاب ولی ناکارآمد | Playwright، code/source UX و accessibility |
| تصاویر بدون context | alt + surrounding text + metadata + selective Vision |
| telemetry بیش‌ازحد پیچیده | پشته‌ی محدود Prometheus/Grafana/Loki/Alloy؛ خارج از مسیر درخواست |
| نبود داده‌ی FAQ واقعی | عنوان «پرسش‌های مرتبط» و feedback loop |

---

## 33. تصمیم‌های قطعی

- Backend: FastAPI.
- Frontend: React + TypeScript + Vite + shadcn/ui.
- Python dependencies: uv + committed lockfile.
- Embedding: `text-embedding-3-large`.
- Embedding production از API؛ GPU شخصی خارج از production.
- Chat/Embedding APIها OpenAI-compatible و قابل‌تنظیم.
- Gateway: Portkey — **image خودمان به‌عنوان app service لیارا**، نه SaaS شرکت Portkey.
- استقرار: همه‌ی سرویس‌ها روی لیارا. توسعه‌ی محلی با Docker Desktop و `docker compose`. هیچ سرویسی self-host نیست.
- Migration دیتابیس: **Alembic**، برای هر تغییر schema بدون استثنا.
- Primary AI provider: AvalAI.
- مدل Chat و FAQ: `gemini-3.7-flash`.
- **ابعاد embedding: `1536`** — نه ۳۰۷۲ (سقف ایندکس HNSW در pgvector برابر ۲۰۰۰ است).
- Observability LLM/RAG: Opik به‌صورت **SaaS** — تنها وابستگی خارجی پروژه.
- Runtime telemetry: **structured JSON logging + شمارنده در PostgreSQL + Prometheus/Grafana/Loki/Alloy**؛ ارسال telemetry best-effort و خارج از مسیر درخواست است.
- State: PostgreSQL.
- Vector store: pgvector در PostgreSQL برای کاهش تعداد سرویس‌ها.
- Queue/cache/rate limit/SSE relay: Redis.
- Chat: bounded Agentic RAG با native function calling، نه Agent آزاد.
- اجرای Chat: worker پشت صف، با relay توکن‌ها از طریق Redis Streams به SSE.
- Web از **همان origin مربوط به API** سرو شود.
- تصاویر: metadata + alt/context embedding. Vision fallback در P1.
- FAQ: تولیدشده با LLM از روی مستندات، سپس curate توسط ادمین.
- احراز هویت: فقط ادمین، HTTP Basic از environment. بدون login برای کاربر نهایی.
- واحد آستانه: **similarity**، نه distance.
- Evaluation: ۱۰ سؤال golden انسانی به‌عنوان دروازه + داور LLM با مدلی **متفاوت** از مدل تحت آزمون.
- CI/CD: GitHub Actions — فقط `ci.yml` و `deploy.yml`.
- مقصد deployment: Liara — **در ساعت اول**.
- زمان: **حداکثر دو روز**، یک توسعه‌دهنده.
- MCP، Skill، Chat، FAQ و dashboard همگی باید در دمو عملیاتی باشند.

---

## 34. تصمیم‌های Configurable یا هنوز باز

این موارد implementation blocker نیستند و باید از environment/config قابل‌تغییر باشند:

- **دامنه‌ی ingestion (`INGEST_SECTIONS`)** — شیر فشار اصلی زمان. پیش‌فرض: کل مستندات.
- Provider و مدل fallback.
- chunk size و overlap.
- FAQ similarity threshold و top-k — threshold از پنل ادمین.
- retrieval top-k و fusion weights.
- token budget، سقف tool call و timeout.
- rate limit thresholds.
- cache TTL.
- `reasoning_effort` برای chat و برای تولید انبوه FAQ.
- مدل داور evaluation.

### هنوز باز — ولی مسدودکننده نیستند

- **کیفیت پاسخ فارسی `gemini-3.7-flash`.** بنچمارک‌های اعلام‌شده روی وظایف کدنویسی انگلیسی هستند و چیزی درباره‌ی فارسی نمی‌گویند. قبل از قفل‌کردن، حدود ۱۰ سؤال به‌صورت دستی بررسی شود. اگر ضعیف بود فقط `LLM_MODEL` عوض می‌شود.
- **در دسترس بودن `pg_trgm` روی لیارا.** تعیین می‌کند تطبیق فازی فارسی اضافه شود یا نه؛ `tsvector` به‌تنهایی برای ship کافی است.
- **انتخاب نهایی provider دوم.** الزام فقط این است که یکی وجود داشته باشد و از شبکه‌ی استقرار در دسترس باشد.
- **تعداد نهایی chunkها و پارامترهای ساخت HNSW.** فقط بعد از اولین ingestion کامل قابل اندازه‌گیری است.

---

## 35. منابع اصلی

- Liara Docs Repository: `https://github.com/liara-cloud/docs`
- Liara Documentation: `https://docs.liara.ir/`
- OpenSpec: `https://github.com/Fission-AI/OpenSpec`
- Opik: `https://github.com/comet-ml/opik`
- Portkey Gateway: `https://github.com/portkey-ai/gateway`
- shadcn/ui LLM Index: `https://ui.shadcn.com/llms.txt`
- UI/UX Pro Max: `https://github.com/nextlevelbuilder/ui-ux-pro-max-skill`

### اسناد داخلی پروژه

- `docs/deployment.md` — زیرساخت، مدل‌ها، هزینه، پیکربندی، pre-pass مربوط به MDX، taxonomy خطاها.
- `docs/eval/golden-set.md` — ۱۰ سؤال golden انسانی.
- `AGENTS.md` — نقطه‌ی ورود canonical برای همه‌ی Coding Agentها.
- `RULES.md` — قواعد مهندسی؛ بخش ۱ آن قاعده‌ی دقیق‌بودن خطاهاست.
- `openspec/changes/add-docs-rescue-assistant/` — proposal، ۸ spec، design و tasks.
