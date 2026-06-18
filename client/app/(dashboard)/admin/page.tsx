import Link from "next/link";
import { ArrowRight, AlertTriangle, ShieldCheck, ShieldAlert } from "lucide-react";

import { StatsCards } from "@/components/admin/stats-cards";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { backend, type ProxyStatus } from "@/lib/backend";

export const dynamic = "force-dynamic";

export default async function AdminOverviewPage() {
  let stats;
  let proxyStatus: ProxyStatus | null = null;
  let error: string | null = null;

  try {
    [stats, proxyStatus] = await Promise.all([
      backend.stats(),
      backend.proxyStatus().catch(() => null),
    ]);
  } catch (err) {
    error = String(err);
  }

  return (
    <div className="h-full overflow-y-auto">
      <header className="flex h-14 items-center justify-between border-b px-6">
        <div>
          <h1 className="text-sm font-semibold">Admin Overview</h1>
          <p className="text-xs text-muted-foreground">
            Aggregate metrics across every query the agent has processed.
          </p>
        </div>
        <Button asChild variant="outline" size="sm">
          <Link href="/admin/logs">
            View audit logs <ArrowRight className="ml-1 h-3 w-3" />
          </Link>
        </Button>
      </header>

      <div className="space-y-6 p-6">
        {proxyStatus && <ProxyStatusCard status={proxyStatus} />}

        {error ? (
          <Card className="border-destructive/40">
            <CardContent className="flex items-center gap-3 py-4 text-sm">
              <AlertTriangle className="h-4 w-4 text-destructive" />
              <span>Unable to reach backend: {error}</span>
            </CardContent>
          </Card>
        ) : stats ? (
          <>
            <StatsCards stats={stats} />
            <BlockBreakdown breakdown={stats.block_breakdown} />
          </>
        ) : null}
      </div>
    </div>
  );
}

function ProxyStatusCard({ status }: { status: ProxyStatus }) {
  const ok = status.reachable;
  return (
    <Card className={ok ? "border-border" : "border-destructive/40"}>
      <CardHeader className="pb-2">
        <div className="flex items-center gap-2">
          {ok ? (
            <ShieldCheck className="h-4 w-4 text-green-600" />
          ) : (
            <ShieldAlert className="h-4 w-4 text-destructive" />
          )}
          <CardTitle className="text-sm">Safety Gateway</CardTitle>
          <Badge
            variant={ok ? "secondary" : "destructive"}
            className="ml-auto text-[10px]"
          >
            {ok ? "ACTIVE" : "OFFLINE"}
          </Badge>
        </div>
        <CardDescription className="text-xs">{status.note}</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="flex gap-6 text-xs text-muted-foreground">
          <span>
            Endpoint: <code className="font-mono text-foreground">{status.proxy_endpoint}</code>
          </span>
          {status.http_status !== null && (
            <span>
              HTTP: <code className="font-mono text-foreground">{status.http_status}</code>
            </span>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function BlockBreakdown({ breakdown }: { breakdown: Record<string, number> }) {
  const entries = Object.entries(breakdown).sort((a, b) => b[1] - a[1]);
  return (
    <Card>
      <CardHeader>
        <CardTitle>Block Reasons</CardTitle>
        <CardDescription>How blocked queries were classified.</CardDescription>
      </CardHeader>
      <CardContent>
        {entries.length === 0 ? (
          <p className="text-sm text-muted-foreground">No blocked queries yet.</p>
        ) : (
          <div className="space-y-2">
            {entries.map(([flag, count]) => (
              <div key={flag} className="flex items-center justify-between rounded-md border border-border px-3 py-2 text-sm">
                <Badge variant="outline" className="font-mono text-xs">
                  {flag}
                </Badge>
                <span className="font-medium tabular-nums">{count}</span>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
