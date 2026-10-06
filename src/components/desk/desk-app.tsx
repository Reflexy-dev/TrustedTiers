import { useState } from "react";
import {
  Download,
  Hash,
  Lock,
  Menu,
  RotateCcw,
  Swords,
  Axe,
  Apple,
  Gem,
  Flame,
  Shield,
  House,
  Anchor,
  Hammer,
  ShoppingCart,
  Hexagon,
  Eye,
  EyeOff,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Sheet, SheetContent } from "@/components/ui/sheet";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  GAMEMODES,
  HIGH_TIERS,
  STANDARD_TIERS,
  PERSONAS,
  type ChannelId,
  type Gamemode,
  type QueueEntry,
  type Persona,
  type Tier,
  canHighTest,
  canSeeMatch,
  canSeeWaitlist,
  canTest,
  isHighEligible,
  personaById,
  rankOf,
  useDesk,
  waitlistWhy,
} from "@/lib/tierlist/model";
import { cn } from "@/lib/utils";

const GM_ICON: Record<Gamemode, typeof Swords> = {
  Sword: Swords,
  Axe: Axe,
  UHC: Apple,
  DiaPot: Gem,
  NethPot: Flame,
  DiaSMP: Shield,
  SMP: House,
  SpearMace: Anchor,
  Mace: Hammer,
  Cart: ShoppingCart,
  Crystal: Hexagon,
};

function initials(name: string) {
  return name.slice(0, 1).toUpperCase();
}

export function DeskApp() {
  const personaId = useDesk((s) => s.personaId);
  const selected = useDesk((s) => s.selected);
  const notice = useDesk((s) => s.notice);
  const setPersona = useDesk((s) => s.setPersona);
  const resetWorld = useDesk((s) => s.resetWorld);
  const clearNotice = useDesk((s) => s.clearNotice);
  const [mobileNav, setMobileNav] = useState(false);
  const persona = personaById(personaId);

  return (
    <div className="flex min-h-dvh flex-col bg-bg text-fg">
      <header className="border-b border-border px-4 py-3 md:px-6">
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-3 min-w-0">
            <Button
              variant="ghost"
              size="icon"
              className="lg:hidden shrink-0"
              aria-label="Canali"
              onClick={() => setMobileNav(true)}
            >
              <Menu />
            </Button>
            <div className="min-w-0">
              <p className="font-mono text-2xs uppercase tracking-label text-muted">
                Combat tierlist
              </p>
              <h1 className="font-display text-2xl font-medium tracking-tight leading-tight">
                Rank Desk
              </h1>
            </div>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <Button variant="ghost" size="sm" onClick={resetWorld} className="hidden sm:inline-flex">
              <RotateCcw />
              Reset
            </Button>
            <Button asChild size="sm">
              <a href="/tierlist-bot.py" download="tierlist-bot.py">
                <Download />
                <span className="hidden sm:inline">Scarica bot</span>
                <span className="sm:hidden">Bot</span>
              </a>
            </Button>
          </div>
        </div>
        <p className="mt-3 max-w-3xl text-sm text-muted">
          I tester vedono sempre la coda della propria gamemode. Tutti gli altri la
          vedono solo quando un tester si mette attivo. I tester non possono
          testare fuori dalla propria lista.
        </p>
      </header>

      <PersonaStrip persona={persona} onPick={setPersona} />

      {notice ? (
        <div className="border-b border-border bg-surface-2 px-4 py-2 md:px-6">
          <div className="flex items-center justify-between gap-3">
            <p className="text-sm text-fg">{notice}</p>
            <button
              type="button"
              className="text-xs text-muted hover:text-fg"
              onClick={clearNotice}
            >
              Chiudi
            </button>
          </div>
        </div>
      ) : null}

      <div className="flex min-h-0 flex-1">
        <aside className="hidden w-64 shrink-0 border-r border-border bg-surface lg:flex lg:flex-col">
          <ChannelRail onPick={() => undefined} />
        </aside>
        <main className="min-w-0 flex-1">
          <ChannelPane key={`${personaId}-${selected}`} />
        </main>
      </div>

      <Sheet open={mobileNav} onOpenChange={setMobileNav}>
        <SheetContent side="left" className="bg-surface pt-12">
          <ChannelRail onPick={() => setMobileNav(false)} />
        </SheetContent>
      </Sheet>
    </div>
  );
}

function PersonaStrip({
  persona,
  onPick,
}: {
  persona: Persona;
  onPick: (id: string) => void;
}) {
  return (
    <div className="border-b border-border bg-surface">
      <div className="flex gap-2 overflow-x-auto px-4 py-3 md:px-6">
        {PERSONAS.map((p) => {
          const active = p.id === persona.id;
          return (
            <button
              key={p.id}
              type="button"
              onClick={() => onPick(p.id)}
              className={cn(
                "flex min-h-11 shrink-0 items-center gap-2 rounded-md border px-3 text-left transition-colors duration-quick",
                active
                  ? "border-accent bg-accent text-accent-fg"
                  : "border-border bg-bg text-fg hover:bg-surface-2",
              )}
            >
              <span
                className={cn(
                  "grid size-7 place-items-center rounded-sm font-mono text-xs",
                  active ? "bg-accent-fg/10" : "bg-surface-2 text-muted",
                )}
              >
                {initials(p.name)}
              </span>
              <span>
                <span className="block text-sm font-medium leading-none">{p.name}</span>
                <span className={cn("mt-1 block text-2xs", active ? "opacity-80" : "text-muted")}>
                  {p.title}
                </span>
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function ChannelRail({ onPick }: { onPick: () => void }) {
  const persona = personaById(useDesk((s) => s.personaId));
  const selected = useDesk((s) => s.selected);
  const select = useDesk((s) => s.select);
  const activeTesters = useDesk((s) => s.activeTesters);
  const activeHighTesters = useDesk((s) => s.activeHighTesters);
  const matches = useDesk((s) => s.matches);
  const queues = useDesk((s) => s.queues);
  const highQueues = useDesk((s) => s.highQueues);

  const waitlists = GAMEMODES.filter((gm) =>
    canSeeWaitlist(persona, gm, false, activeTesters, activeHighTesters),
  );
  const highWaitlists = GAMEMODES.filter((gm) =>
    canSeeWaitlist(persona, gm, true, activeTesters, activeHighTesters),
  );
  const visibleMatches = matches.filter((m) => canSeeMatch(persona, m));

  const hiddenCount =
    GAMEMODES.length * 2 - waitlists.length - highWaitlists.length;

  function pick(id: ChannelId) {
    select(id);
    onPick();
  }

  return (
    <ScrollArea className="h-full">
      <nav className="flex flex-col gap-5 p-4">
        <RailGroup label="Pannelli">
          <RailItem
            id="panel"
            selected={selected}
            onClick={() => pick("panel")}
            icon={Hash}
            label="ticket-panel"
          />
          <RailItem
            id="high-panel"
            selected={selected}
            onClick={() => pick("high-panel")}
            icon={Hash}
            label="high-panel"
          />
        </RailGroup>

        <RailGroup label="Code standard">
          {waitlists.length === 0 ? (
            <p className="px-2 text-xs text-faint">Nessuna coda visibile.</p>
          ) : (
            waitlists.map((gm) => (
              <RailItem
                key={gm}
                id={`waitlist-${gm}`}
                selected={selected}
                onClick={() => pick(`waitlist-${gm}`)}
                icon={GM_ICON[gm]}
                label={`waitlist-${gm.toLowerCase()}`}
                count={queues[gm].length}
                live={activeTesters[gm] != null}
                locked={persona.testerOf.includes(gm) && !activeTesters[gm]}
              />
            ))
          )}
        </RailGroup>

        <RailGroup label="High queue">
          {highWaitlists.length === 0 ? (
            <p className="px-2 text-xs text-faint">Nessuna high queue visibile.</p>
          ) : (
            highWaitlists.map((gm) => (
              <RailItem
                key={gm}
                id={`high-waitlist-${gm}`}
                selected={selected}
                onClick={() => pick(`high-waitlist-${gm}`)}
                icon={GM_ICON[gm]}
                label={`high-waitlist-${gm.toLowerCase()}`}
                count={highQueues[gm].length}
                live={activeHighTesters[gm] != null}
                locked={persona.testerOf.includes(gm) && !activeHighTesters[gm]}
              />
            ))
          )}
        </RailGroup>

        <RailGroup label="Match room">
          {visibleMatches.length === 0 ? (
            <p className="px-2 text-xs text-faint">Nessuna room aperta.</p>
          ) : (
            visibleMatches.map((m) => (
              <RailItem
                key={m.id}
                id={`match-${m.id}`}
                selected={selected}
                onClick={() => pick(`match-${m.id}`)}
                icon={Lock}
                label={`${m.high ? "high-" : ""}match-${m.playerName.toLowerCase()}-${m.gamemode.toLowerCase()}`}
              />
            ))
          )}
        </RailGroup>

        <RailGroup label="Log">
          <RailItem
            id="results"
            selected={selected}
            onClick={() => pick("results")}
            icon={Hash}
            label="results"
          />
          <RailItem
            id="high-results"
            selected={selected}
            onClick={() => pick("high-results")}
            icon={Hash}
            label="high-results"
          />
        </RailGroup>

        <p className="px-2 text-2xs leading-relaxed text-faint">
          {hiddenCount} canali coda nascosti per {persona.name}. Compaiono quando
          il tester di quella gamemode si mette attivo.
        </p>
      </nav>
    </ScrollArea>
  );
}

function RailGroup({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="mb-1.5 px-2 font-mono text-3xs uppercase tracking-label text-faint">
        {label}
      </p>
      <div className="flex flex-col gap-0.5">{children}</div>
    </div>
  );
}

function RailItem({
  id,
  selected,
  onClick,
  icon: Icon,
  label,
  count,
  live,
  locked,
}: {
  id: string;
  selected: string;
  onClick: () => void;
  icon: typeof Hash;
  label: string;
  count?: number;
  live?: boolean;
  locked?: boolean;
}) {
  const active = selected === id;
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex min-h-11 min-w-0 items-center gap-2 overflow-hidden rounded-sm px-2 text-left text-sm transition-colors duration-quick",
        active ? "bg-surface-2 text-fg" : "text-muted hover:bg-bg hover:text-fg",
      )}
    >
      <Icon className="size-4 shrink-0" aria-hidden />
      <span className="min-w-0 flex-1 truncate font-mono text-sm">{label}</span>
      {locked ? <Eye className="size-3.5 shrink-0 text-faint" /> : null}
      {live ? <span className="size-1.5 shrink-0 rounded-full bg-ok" /> : null}
      {count ? (
        <span className="font-mono text-2xs tabular-nums text-faint">{count}</span>
      ) : null}
    </button>
  );
}

function ChannelPane() {
  const selected = useDesk((s) => s.selected);
  if (selected === "panel") return <TicketPanel high={false} />;
  if (selected === "high-panel") return <TicketPanel high />;
  if (selected === "results") return <ResultsPane high={false} />;
  if (selected === "high-results") return <ResultsPane high />;
  if (selected.startsWith("waitlist-")) {
    return <WaitlistPane gm={selected.replace("waitlist-", "") as Gamemode} high={false} />;
  }
  if (selected.startsWith("high-waitlist-")) {
    return <WaitlistPane gm={selected.replace("high-waitlist-", "") as Gamemode} high />;
  }
  if (selected.startsWith("match-")) {
    return <MatchPane id={selected.replace("match-", "")} />;
  }
  return <TicketPanel high={false} />;
}

function PaneHeader({
  title,
  hint,
}: {
  title: string;
  hint: string;
}) {
  return (
    <div className="border-b border-border px-4 py-4 md:px-8">
      <div className="flex items-center gap-2 text-muted">
        <Hash className="size-4" />
        <h2 className="font-mono text-sm text-fg">{title}</h2>
      </div>
      <p className="mt-1.5 text-sm text-muted">{hint}</p>
    </div>
  );
}

function TicketPanel({ high }: { high: boolean }) {
  const [open, setOpen] = useState<Gamemode | null>(null);
  const persona = personaById(useDesk((s) => s.personaId));
  const joinQueue = useDesk((s) => s.joinQueue);
  const leaveQueue = useDesk((s) => s.leaveQueue);
  const [error, setError] = useState<string | null>(null);

  return (
    <div>
      <PaneHeader
        title={high ? "high-panel" : "ticket-panel"}
        hint={
          high
            ? "High Tiers · serve LT3 o superiore nella gamemode scelta."
            : "Clicca una gamemode per entrare in coda. Il canale waitlist non si apre a te: compare a tutti solo se un tester è attivo."
        }
      />
      <div className="grid grid-cols-2 gap-2 p-4 sm:grid-cols-3 md:grid-cols-4 md:p-8">
        {GAMEMODES.map((gm) => {
          const Icon = GM_ICON[gm];
          const lockedHigh = high && !isHighEligible(persona, gm) && !persona.isAdmin;
          return (
            <button
              key={gm}
              type="button"
              onClick={() => {
                setError(null);
                if (lockedHigh) {
                  setError(`Serve LT3 in ${gm}. Rank: ${rankOf(persona, gm)}.`);
                  return;
                }
                setOpen(gm);
              }}
              className="flex min-h-20 flex-col items-start gap-2 rounded-md border border-border bg-surface p-3 text-left hover:bg-surface-2"
            >
              <Icon className="size-4 text-muted" />
              <span className="text-sm font-medium">{gm}</span>
              {lockedHigh ? (
                <span className="text-2xs text-faint">Bloccato</span>
              ) : null}
            </button>
          );
        })}
      </div>
      <div className="px-4 pb-8 md:px-8">
        {error ? <p className="mb-3 text-sm text-danger">{error}</p> : null}
        <Button variant="outline" onClick={() => setError(leaveQueue())}>
          Esci dalla coda
        </Button>
      </div>
      <JoinDialog
        gm={open}
        high={high}
        onClose={() => setOpen(null)}
        onJoin={(gmName, mc, region) => {
          const err = joinQueue(gmName, high, mc, region);
          if (err) {
            setError(err);
            return false;
          }
          setError(null);
          return true;
        }}
      />
    </div>
  );
}

function JoinDialog({
  gm,
  high,
  onClose,
  onJoin,
}: {
  gm: Gamemode | null;
  high: boolean;
  onClose: () => void;
  onJoin: (gm: Gamemode, mc: string, region: string) => boolean;
}) {
  const persona = personaById(useDesk((s) => s.personaId));
  const [mc, setMc] = useState(persona.name);
  const [region, setRegion] = useState("EU");

  return (
    <Dialog
      open={gm != null}
      onOpenChange={(v) => {
        if (!v) onClose();
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {high ? "High queue" : "Coda"} {gm}
          </DialogTitle>
          <DialogDescription>
            Entri in lista. Il canale waitlist resta nascosto finché un tester
            non si mette attivo — a meno che tu non sia tester di questa
            gamemode.
          </DialogDescription>
        </DialogHeader>
        <form
          className="mt-4 flex flex-col gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            if (!gm) return;
            const ok = onJoin(gm, mc, region);
            if (ok) onClose();
          }}
        >
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="mc">Username Minecraft</Label>
            <Input id="mc" value={mc} onChange={(e) => setMc(e.target.value)} required />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="region">Region</Label>
            <Input
              id="region"
              value={region}
              onChange={(e) => setRegion(e.target.value)}
              maxLength={10}
              required
            />
          </div>
          <Button type="submit">Entra in coda</Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function WaitlistPane({ gm, high }: { gm: Gamemode; high: boolean }) {
  const persona = personaById(useDesk((s) => s.personaId));
  const activeTesters = useDesk((s) => s.activeTesters);
  const activeHighTesters = useDesk((s) => s.activeHighTesters);
  const queues = useDesk((s) => s.queues);
  const highQueues = useDesk((s) => s.highQueues);
  const joinAsTester = useDesk((s) => s.joinAsTester);
  const leaveTester = useDesk((s) => s.leaveTester);
  const nextPlayer = useDesk((s) => s.nextPlayer);
  const [error, setError] = useState<string | null>(null);

  const list = high ? highQueues[gm] : queues[gm];
  const testerId = high ? activeHighTesters[gm] : activeTesters[gm];
  const tester = testerId ? personaById(testerId) : null;
  const why = waitlistWhy(persona, gm, high, activeTesters, activeHighTesters);
  const staffOk = high ? canHighTest(persona, gm) : canTest(persona, gm);
  const iAmActive = testerId === persona.id;

  return (
    <div>
      <PaneHeader
        title={`${high ? "high-waitlist" : "waitlist"}-${gm.toLowerCase()}`}
        hint={why}
      />
      <div className="space-y-6 p-4 md:p-8">
        <div className="rounded-lg border border-border bg-surface p-5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="font-medium">
              {high ? "High Queue" : "Queue"} {gm}
            </p>
            <Badge variant={tester ? "ok" : "default"}>
              {tester ? `Tester attivo: ${tester.name}` : "Nessun tester attivo"}
            </Badge>
          </div>
          <p className="mt-1 text-sm text-muted">
            {list.length}/20 in attesa
          </p>
          <ol className="mt-4 space-y-1.5">
            {list.length === 0 ? (
              <li className="text-sm text-faint">Vuota</li>
            ) : (
              list.map((p, i) => <QueueRow key={p.userId} index={i} entry={p} />)
            )}
          </ol>
        </div>

        {staffOk ? (
          <div className="flex flex-col gap-2 sm:flex-row">
            {iAmActive ? (
              <Button
                variant="secondary"
                onClick={() => setError(leaveTester(gm, high))}
              >
                <EyeOff />
                Lascia sessione tester
              </Button>
            ) : (
              <Button
                onClick={() => setError(joinAsTester(gm, high))}
              >
                <Eye />
                Unisciti come tester
              </Button>
            )}
            <Button
              variant="secondary"
              onClick={() => setError(nextPlayer(gm, high))}
            >
              Prossimo giocatore
            </Button>
          </div>
        ) : (
          <p className="text-sm text-muted">
            Controlli staff riservati a Tester {gm}
            {high ? " con rank LT3 o superiore" : ""}. Puoi vedere il canale,
            ma non testare questa gamemode.
          </p>
        )}
        {error ? <p className="text-sm text-danger">{error}</p> : null}

        <div className="rounded-md border border-border bg-bg p-4 text-sm text-muted">
          {persona.testerOf.includes(gm) ? (
            <p>
              Questo canale resta nella tua lista anche a tester spento: è la
              tua gamemode.
            </p>
          ) : persona.isAdmin ? (
            <p>Come admin vedi tutte le code, attive o meno.</p>
          ) : (
            <p>
              Lo vedi solo perché un tester è attivo. Se lascia la sessione, il
              canale scompare dalla tua sidebar.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

function QueueRow({ index, entry }: { index: number; entry: QueueEntry }) {
  return (
    <li className="flex items-center gap-3 rounded-sm bg-bg px-3 py-2">
      <span className="font-mono text-xs tabular-nums text-faint">{index + 1}</span>
      <span className="grid size-7 place-items-center rounded-sm bg-surface-2 font-mono text-xs text-muted">
        {initials(entry.name)}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-sm">{entry.name}</span>
        <span className="block font-mono text-2xs text-faint">
          {entry.mcName} · {entry.region}
        </span>
      </span>
    </li>
  );
}

function MatchPane({ id }: { id: string }) {
  const matches = useDesk((s) => s.matches);
  const submitResult = useDesk((s) => s.submitResult);
  const persona = personaById(useDesk((s) => s.personaId));
  const match = matches.find((m) => m.id === id);
  const [earned, setEarned] = useState<Tier>(match?.high ? "HT3" : "LT4");
  const [error, setError] = useState<string | null>(null);

  if (!match) {
    return (
      <div className="p-8 text-sm text-muted">Match room chiusa.</div>
    );
  }

  const isTesterHere = persona.id === match.testerId || persona.isAdmin;
  const options = match.high ? HIGH_TIERS : STANDARD_TIERS;

  return (
    <div>
      <PaneHeader
        title={`${match.high ? "high-" : ""}match-${match.playerName.toLowerCase()}-${match.gamemode.toLowerCase()}`}
        hint="Stanza privata: visibile solo a tester e giocatore di questo test."
      />
      <div className="space-y-6 p-4 md:p-8">
        <div className="rounded-lg border border-border bg-surface p-5">
          <p className="font-medium">
            {match.playerName} vs {match.testerName}
          </p>
          <p className="mt-1 font-mono text-sm text-muted">
            {match.mcName} · {match.region} · {match.gamemode}
            {match.high ? " · High" : ""}
          </p>
        </div>
        {isTesterHere ? (
          <form
            className="flex max-w-sm flex-col gap-3"
            onSubmit={(e) => {
              e.preventDefault();
              setError(submitResult(match.id, earned));
            }}
          >
            <Label htmlFor="rank">Rank assegnato</Label>
            <select
              id="rank"
              value={earned}
              onChange={(e) => setEarned(e.target.value as Tier)}
              className="h-11 rounded-sm border border-border bg-surface px-3 text-sm"
            >
              {options.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
            <Button type="submit">Pubblica risultato</Button>
            {error ? <p className="text-sm text-danger">{error}</p> : null}
          </form>
        ) : (
          <p className="text-sm text-muted">In attesa del risultato del tester.</p>
        )}
      </div>
    </div>
  );
}

function ResultsPane({ high }: { high: boolean }) {
  const results = useDesk((s) => s.results).filter((r) => r.high === high);
  return (
    <div>
      <PaneHeader
        title={high ? "high-results" : "results"}
        hint="Canale pubblico dei risultati."
      />
      <div className="space-y-3 p-4 md:p-8">
        {results.length === 0 ? (
          <p className="text-sm text-faint">Nessun risultato ancora.</p>
        ) : (
          results.map((r) => (
            <div key={r.id} className="rounded-md border border-border bg-surface p-4">
              <p className="text-sm font-medium">
                {r.playerName} · {r.mcName}
              </p>
              <p className="mt-1 font-mono text-xs text-muted">
                {r.gamemode} · {r.prev} → {r.earned} · tester {r.testerName}
              </p>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
