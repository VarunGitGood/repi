import Link from "next/link"
import {
  Search, Bot, Eye, Layers, Clock, Database, Globe, ArrowRight,
} from "lucide-react"
import { Brand } from "@/components/brand"
import { isPublicMode } from "@/lib/public-mode"

function GithubIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" className={className} aria-hidden>
      <path d="M12 0C5.374 0 0 5.373 0 12c0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23A11.509 11.509 0 0 1 12 5.803c1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576C20.566 21.797 24 17.3 24 12c0-6.627-5.373-12-12-12z" />
    </svg>
  )
}

function LinkedinIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" className={className} aria-hidden>
      <path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433a2.062 2.062 0 0 1-2.063-2.065 2.064 2.064 0 1 1 2.063 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z" />
    </svg>
  )
}
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Separator } from "@/components/ui/separator"
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table"
import { ThemeToggle } from "@/components/docs/theme-toggle"
import { CodeBlock } from "@/components/docs/code-block"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"

// ─── Data ─────────────────────────────────────────────────────────────────────

const FEATURES = [
  {
    icon: Search,
    title: "Hybrid Search",
    description:
      "ParadeDB BM25 full-text search + pgvector HNSW dense retrieval fused with Reciprocal Rank Fusion for best-of-both recall.",
  },
  {
    icon: Bot,
    title: "Autonomous ReAct Loop",
    description:
      "LLM thinks, calls tools, observes results — up to 10 iterations per investigation to surface the actual root cause.",
  },
  {
    icon: Eye,
    title: "Background File Watcher",
    description:
      "Register a directory via API. The worker ingests new log bytes automatically, tracking byte offsets per file.",
  },
  {
    icon: Layers,
    title: "Multi-LLM",
    description:
      "OpenAI, Anthropic, Mistral, Gemini, Ollama — swap your provider with one line of .repi/config.json (or one click in the UI).",
  },
  {
    icon: Clock,
    title: "Progressive Time Windows",
    description:
      "Investigations start narrow and automatically expand their search window when results are sparse.",
  },
  {
    icon: Database,
    title: "Full Audit Trail",
    description:
      "Every thought, tool call, and observation is persisted to PostgreSQL. Replay any investigation step by step.",
  },
]

interface InstallPath {
  value: string
  label: string
  tagline: string
  prereqs: string
  code: string
}

const INSTALL_PATHS: InstallPath[] = [
  {
    value: "docker",
    label: "Docker",
    tagline: "Prebuilt image. Backend + UI + Postgres + Redis in one compose stack.",
    prereqs: "Docker, git",
    code: `# Get the compose file (clone or copy from GitHub)
git clone https://github.com/VarunGitGood/repi.git && cd repi

# Pulls ghcr.io/varungitgood/repi:latest and starts db + redis + app
docker compose up -d

# Open http://localhost:3000 → Config → paste your LLM key → save`,
  },
  {
    value: "local",
    label: "Local dev",
    tagline: "Hack on the code with hot-reload. Docker runs only db + redis; backend + UI run on the host.",
    prereqs: "Docker, Python 3.11+, uv, Node.js",
    code: `git clone https://github.com/VarunGitGood/repi.git && cd repi
uv sync

# db + redis up, prompts provider/key, writes .repi/config.json, applies schema
uv run repi init --with-docker

# Terminal 1: API on :8000 (auto-reload in development)
uv run repi serve

# Terminal 2: web UI on :3000 (Next.js HMR)
uv run repi ui`,
  },
  {
    value: "image",
    label: "Pull image",
    tagline: "Just grab the multi-arch image. Bring your own Postgres + Redis.",
    prereqs: "Docker, a running Postgres (with pgvector) and Redis",
    code: `# Pull the latest published image (~500 MB, multi-arch)
docker pull ghcr.io/varungitgood/repi:latest

# Or pin a release
docker pull ghcr.io/varungitgood/repi:v0.1.0`,
  },
]

const REGISTER_WATCHER_CODE = `curl -X POST http://localhost:8000/watchers \\
  -H "Content-Type: application/json" \\
  -d '{"service_name": "auth-svc", "watch_path": "/var/log/auth"}'`

const ENV_VARS = [
  {
    name: "REPI_ENV",
    default: "production",
    description: "production | development. Production is quiet (uvicorn log_level=warning, no reload). Development is verbose.",
  },
  {
    name: "LOG_LEVEL",
    default: "INFO",
    description: "DEBUG | INFO | WARNING | ERROR. Overridden to DEBUG when REPI_ENV is development.",
  },
  {
    name: "DATABASE_URL",
    default: "postgresql+asyncpg://repi_user:password_here@localhost:5432/repi",
    description: "PostgreSQL asyncpg connection URL",
  },
  {
    name: "LLM_PROVIDER",
    default: "openai",
    description: "openai | anthropic | mistral | gemini | ollama",
  },
  {
    name: "LLM_MODEL",
    default: "provider default",
    description: "Override the default model for the selected provider",
  },
  {
    name: "OPENAI_API_KEY",
    default: "—",
    description: "Provider API key (also ANTHROPIC_API_KEY, MISTRAL_API_KEY, GEMINI_API_KEY)",
  },
  {
    name: "REDIS_URL",
    default: "redis://localhost:6379",
    description: "Redis connection URL for response caching",
  },
  {
    name: "ENABLE_REDIS_CACHE",
    default: "true",
    description: "Set false to disable Redis caching",
  },
  {
    name: "TIME_WINDOW_INITIAL_MINUTES",
    default: "10",
    description: "Starting time window for investigations (minutes)",
  },
  {
    name: "TIME_WINDOW_EXPANSIONS",
    default: "60,360,1440",
    description: "Progressive window expansion in minutes (1h → 6h → 24h)",
  },
  {
    name: "UI_PORT",
    default: "3000",
    description: "Port the web UI binds to",
  },
  {
    name: "WATCHER_CONFIG_REFRESH_SECS",
    default: "30",
    description: "How often the worker polls DB for config changes",
  },
  {
    name: "OLLAMA_BASE_URL",
    default: "http://localhost:11434",
    description: "Ollama API endpoint",
  },
]

// ─── Page ──────────────────────────────────────────────────────────────────────

export default function DocsPage() {
  const publicDeploy = isPublicMode()
  return (
    <div className="min-h-screen selection:bg-foreground selection:text-background">
      {/* Background dot grid / ambient glow / noise lives in <Background />
          (mounted by the root layout). Pages don't render their own blurs. */}

      {/* ── Docs Navbar ───────────────────────────────────────────────────────── */}
      <nav className="sticky top-0 z-40 w-full border-b bg-background/80 backdrop-blur-md">
        <div className="max-w-7xl mx-auto px-6 h-14 flex items-center justify-between">
          <div className="flex items-center gap-6">
            <div className="flex items-center gap-2.5">
              <Brand size={28} />
              <span className="font-bold tracking-tight text-base">repi</span>
              <Badge variant="outline" className="text-[10px] uppercase tracking-widest font-bold py-0 h-5 px-1.5 opacity-60">
                docs
              </Badge>
            </div>
            <Separator orientation="vertical" className="h-4 hidden sm:block opacity-20" />
            <div className="hidden md:flex items-center gap-8 text-sm font-medium">
              <a href="#features" className="text-muted-foreground hover:text-foreground transition-all">Features</a>
              <a href="#quickstart" className="text-muted-foreground hover:text-foreground transition-all">Quick Start</a>
              <a href="#worker" className="text-muted-foreground hover:text-foreground transition-all">Worker</a>
              <a href="#env-vars" className="text-muted-foreground hover:text-foreground transition-all">Config</a>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <ThemeToggle />
            <a
              href="https://github.com/VarunGitGood/repi"
              target="_blank"
              rel="noopener noreferrer"
              aria-label="GitHub"
              className="hover:scale-105 transition-transform"
            >
              <Button variant="ghost" size="icon" className="h-9 w-9">
                <GithubIcon className="h-4 w-4" />
              </Button>
            </a>
            {!publicDeploy && (
              <Link
                href="/"
                className="ml-1 inline-flex items-center gap-1.5 rounded-full bg-foreground text-background text-xs font-medium px-3 h-8 hover:opacity-90 transition-opacity"
              >
                Open Chat
                <ArrowRight className="h-3.5 w-3.5" />
              </Link>
            )}
          </div>
        </div>
      </nav>

      <div className="relative z-10">
        {/* ── Hero ──────────────────────────────────────────────────────────────── */}
        <section className="relative flex flex-col items-center justify-center text-center px-6 py-40 sm:py-56 overflow-hidden">
          <div className="inline-flex items-center gap-2 text-[10px] uppercase tracking-[0.2em] font-bold text-muted-foreground border rounded-full px-4 py-1.5 mb-10 bg-background/50 backdrop-blur-sm">
            <span>Open-source</span>
            <span className="opacity-30">/</span>
            <span>Self-hosted</span>
            <span className="opacity-30">/</span>
            <span>Any LLM</span>
          </div>
          <h1 className="text-6xl sm:text-8xl font-black tracking-normal mb-8 max-w-4xl leading-[0.9] text-balance">
            Stop grepping.<br />
            <span className="text-muted-foreground/40">Start knowing.</span>
          </h1>
          <p className="text-xl text-muted-foreground max-w-2xl mb-12 leading-relaxed text-balance font-medium">
            repi ingests logs into PostgreSQL, indexes them with hybrid search (ParadeDB BM25 + pgvector),
            and runs an autonomous ReAct loop to trace root causes across services.
          </p>
          <div className="flex flex-col sm:flex-row gap-4 mb-16">
            <Link href="/?demo=1">
              <Button size="lg" className="rounded-full px-10 h-14 text-base font-bold shadow-xl shadow-foreground/10 hover:shadow-foreground/20 transition-all hover:-translate-y-0.5">
                ▶ Try Demo
              </Button>
            </Link>
            <a
              href="https://github.com/VarunGitGood/repi"
              target="_blank"
              rel="noopener noreferrer"
            >
              <Button size="lg" variant="outline" className="rounded-full px-10 h-14 text-base font-bold bg-background/50 backdrop-blur-sm hover:-translate-y-0.5 transition-all">
                <GithubIcon className="h-5 w-5 mr-2.5" />
                View on GitHub
              </Button>
            </a>
          </div>
        </section>

        {/* ── Features ──────────────────────────────────────────────────────────── */}
        <section id="features" className="scroll-mt-32 py-32 px-6 border-t border-foreground/[0.03]">
          <div className="max-w-7xl mx-auto">
            <div className="flex flex-col items-start mb-20">
              <h2 className="text-4xl font-black tracking-tight mb-4">Everything you need to debug faster</h2>
              <p className="text-lg text-muted-foreground max-w-2xl font-medium">
                Built on PostgreSQL and your existing LLM provider. No new infrastructure, no vendor lock-in.
              </p>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
              {FEATURES.map((f) => (
                <div
                  key={f.title}
                  className="group relative border border-foreground/[0.05] rounded-3xl p-8 bg-card/50 backdrop-blur-sm hover:bg-card hover:border-foreground/10 transition-all hover:shadow-2xl hover:shadow-foreground/[0.02]"
                >
                  <div className="mb-6 bg-muted size-12 rounded-2xl flex items-center justify-center group-hover:scale-110 transition-transform">
                    <f.icon className="h-6 w-6" />
                  </div>
                  <h3 className="text-xl font-bold mb-3">{f.title}</h3>
                  <p className="text-muted-foreground leading-relaxed font-medium">{f.description}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* ── Quick Start ───────────────────────────────────────────────────────── */}
        <section id="quickstart" className="scroll-mt-32 py-32 px-6 border-t border-foreground/[0.03] bg-muted/10">
          <div className="max-w-4xl mx-auto">
            <div className="text-center mb-16">
              <h2 className="text-5xl font-black tracking-tight mb-6">Up and running in 5m</h2>
              <p className="text-lg text-muted-foreground font-medium">
                Pick the path that fits how you want to run repi.
              </p>
            </div>
            <Tabs defaultValue="docker" className="!gap-6">
              <TabsList className="self-center">
                {INSTALL_PATHS.map((path) => (
                  <TabsTrigger key={path.value} value={path.value}>
                    {path.label}
                  </TabsTrigger>
                ))}
              </TabsList>
              {INSTALL_PATHS.map((path) => (
                <TabsContent key={path.value} value={path.value} className="space-y-6">
                  <div className="space-y-2">
                    <p className="text-base text-muted-foreground font-medium leading-relaxed">
                      {path.tagline}
                    </p>
                    <p className="text-xs uppercase tracking-widest font-bold text-muted-foreground/70">
                      Prerequisites: <span className="text-foreground/80 normal-case tracking-normal font-medium">{path.prereqs}</span>
                    </p>
                  </div>
                  <div className="shadow-2xl shadow-foreground/[0.02] hover:shadow-foreground/[0.05] transition-shadow rounded-2xl overflow-hidden border border-foreground/[0.03]">
                    <CodeBlock code={path.code} language="bash" />
                  </div>
                </TabsContent>
              ))}
            </Tabs>
          </div>
        </section>

        {/* ── Worker ────────────────────────────────────────────────────────────── */}
        <section id="worker" className="scroll-mt-32 py-32 px-6 border-t border-foreground/[0.03]">
          <div className="max-w-4xl mx-auto">
            <div className="flex flex-col items-start mb-16">
              <h2 className="text-4xl font-black tracking-tight mb-6">Always-on log ingestion</h2>
              <p className="text-lg text-muted-foreground font-medium leading-relaxed max-w-3xl">
                The worker watches directories for new log bytes and ingests them automatically.
                It tracks a byte offset per file so it only processes what&apos;s new — restarts are safe.
              </p>
            </div>
            <div className="grid grid-cols-1 gap-12">
              <div className="space-y-6">
                <div className="flex items-center gap-3">
                  <Badge variant="secondary" className="rounded-md">01</Badge>
                  <h3 className="text-xl font-bold">Register a watcher</h3>
                </div>
                <div className="rounded-2xl overflow-hidden border border-foreground/[0.03] shadow-lg shadow-foreground/[0.01]">
                  <CodeBlock code={REGISTER_WATCHER_CODE} language="bash" />
                </div>
              </div>
              <div className="space-y-6">
                <div className="flex items-center gap-3">
                  <Badge variant="secondary" className="rounded-md">02</Badge>
                  <h3 className="text-xl font-bold">Start the worker</h3>
                </div>
                <div className="rounded-2xl overflow-hidden border border-foreground/[0.03] shadow-lg shadow-foreground/[0.01]">
                  <CodeBlock code="docker compose exec app python -m repi.worker" language="bash" />
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* ── Env Vars ──────────────────────────────────────────────────────────── */}
        <section id="env-vars" className="scroll-mt-32 py-32 px-6 border-t border-foreground/[0.03] bg-muted/5">
          <div className="max-w-7xl mx-auto">
            <div className="flex flex-col items-center text-center mb-20">
              <h2 className="text-4xl font-black tracking-tight mb-4">Configuration</h2>
              <p className="text-lg text-muted-foreground font-medium max-w-2xl">
                All settings live in{" "}
                <code className="font-mono text-sm bg-muted px-2 py-0.5 rounded-md border border-foreground/5">/app/.repi/config.json</code>
                {" "}inside the container — seeded with docker-aware defaults on first boot, then editable via the web UI&apos;s Config page (the API hot-reloads). Shell env vars and{" "}
                <code className="font-mono text-sm bg-muted px-2 py-0.5 rounded-md border border-foreground/5">.env</code>{" "}
                files are intentionally ignored.
              </p>
            </div>
            <div className="rounded-3xl border border-foreground/[0.03] overflow-x-auto bg-background/50 backdrop-blur-sm shadow-2xl shadow-foreground/[0.02]">
              <Table>
                <TableHeader>
                  <TableRow className="hover:bg-transparent border-b border-foreground/[0.03]">
                    <TableHead className="w-[300px] h-14 text-foreground font-bold uppercase tracking-widest text-[10px]">Key</TableHead>
                    <TableHead className="w-[250px] h-14 text-foreground font-bold uppercase tracking-widest text-[10px]">Default</TableHead>
                    <TableHead className="h-14 text-foreground font-bold uppercase tracking-widest text-[10px]">Description</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {ENV_VARS.map((v) => (
                    <TableRow key={v.name} className="border-b border-foreground/[0.03] last:border-0 group hover:bg-muted/30 transition-colors">
                      <TableCell className="py-5">
                        <code className="font-mono text-[13px] bg-muted group-hover:bg-background px-2 py-1 rounded-md border border-foreground/[0.03] transition-colors">
                          {v.name}
                        </code>
                      </TableCell>
                      <TableCell className="py-5">
                        <code className="font-mono text-[13px] text-muted-foreground">
                          {v.default}
                        </code>
                      </TableCell>
                      <TableCell className="py-5 text-[15px] text-muted-foreground font-medium">
                        {v.description}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </div>
        </section>

        {/* ── CTA Band ──────────────────────────────────────────────────────────── */}
        <section className="relative overflow-hidden py-40 px-6 bg-foreground text-background">
          <div className="absolute inset-0 opacity-10">
            <div className="absolute top-0 left-0 w-full h-full bg-[radial-gradient(circle_at_center,var(--background)_1px,transparent_1px)] bg-[size:40px_40px]" />
          </div>
          <div className="relative max-w-3xl mx-auto text-center">
            <h2 className="text-5xl sm:text-7xl font-black tracking-tighter mb-8 text-balance leading-[0.9]">
              Investigate your first incident in under 5 minutes.
            </h2>
            <p className="mb-12 text-xl font-medium opacity-60 text-balance">
              Self-hosted. No data leaves your infrastructure.
            </p>
            <div className="group relative inline-block">
              <div className="absolute inset-0 bg-background/20 blur-xl opacity-0 group-hover:opacity-100 transition-opacity" />
              <div className="relative font-mono text-base bg-background/10 border border-background/20 px-8 py-4 rounded-2xl inline-block backdrop-blur-md">
                <span className="opacity-40 mr-3 select-none">$</span>
                docker compose up -d
              </div>
            </div>
          </div>
        </section>

        {/* ── Footer ────────────────────────────────────────────────────────────── */}
        <footer className="border-t border-foreground/[0.03] pt-24 pb-12 px-6">
          <div className="max-w-7xl mx-auto">
            <div className="grid grid-cols-1 md:grid-cols-4 gap-16 items-start mb-24">
              <div className="md:col-span-2">
                <div className="flex items-center gap-3 mb-6">
                  <Brand size={32} />
                  <span className="font-black text-xl tracking-tight">repi</span>
                </div>
                <p className="text-lg text-muted-foreground leading-relaxed font-medium max-w-sm">
                  Autonomous log investigation powered by ParadeDB, pgvector, and ReAct loops.
                  Open-source, self-hosted, private.
                </p>
              </div>
              <div>
                <p className="font-bold text-xs uppercase tracking-widest mb-6 opacity-40">Docs</p>
                <div className="flex flex-col gap-4 text-base font-medium text-muted-foreground">
                  <a href="#features" className="hover:text-foreground transition-colors">Features</a>
                  <a href="#quickstart" className="hover:text-foreground transition-colors">Quick Start</a>
                  <a href="#worker" className="hover:text-foreground transition-colors">Worker</a>
                  <a href="#env-vars" className="hover:text-foreground transition-colors">Config</a>
                </div>
              </div>
              <div>
                <p className="font-bold text-xs uppercase tracking-widest mb-6 opacity-40">Connect</p>
                <div className="flex gap-3">
                  <a
                    href="https://github.com/VarunGitGood"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="hover:scale-110 transition-transform"
                  >
                    <Button variant="outline" size="icon" className="h-11 w-11 rounded-xl">
                      <GithubIcon className="h-5 w-5" />
                    </Button>
                  </a>
                  <a
                    href="https://www.linkedin.com/in/varun-singh-018242224/"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="hover:scale-110 transition-transform"
                  >
                    <Button variant="outline" size="icon" className="h-11 w-11 rounded-xl">
                      <LinkedinIcon className="h-5 w-5" />
                    </Button>
                  </a>
                  <a
                    href="https://vrun.vercel.app"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="hover:scale-110 transition-transform"
                  >
                    <Button variant="outline" size="icon" className="h-11 w-11 rounded-xl">
                      <Globe className="h-5 w-5" />
                    </Button>
                  </a>
                </div>
              </div>
            </div>
            <div className="pt-12 border-t border-foreground/[0.03] flex flex-col sm:flex-row justify-between items-center gap-6">
              <p className="text-sm text-muted-foreground font-medium">
                © 2026 repi. Built by{" "}
                <a href="https://vrun.vercel.app" className="text-foreground hover:underline underline-offset-4 font-bold">
                  Varun Singh
                </a>
              </p>
              <div className="flex items-center gap-8 text-sm text-muted-foreground font-medium">
                <a href="#" className="hover:text-foreground transition-colors">Privacy</a>
                <a href="#" className="hover:text-foreground transition-colors">Terms</a>
                <a href="https://github.com/VarunGitGood/repi" className="hover:text-foreground transition-colors flex items-center gap-2">
                  <GithubIcon className="h-3.5 w-3.5" />
                  Star on GitHub
                </a>
              </div>
            </div>
          </div>
        </footer>
      </div>
    </div>
  )
}
