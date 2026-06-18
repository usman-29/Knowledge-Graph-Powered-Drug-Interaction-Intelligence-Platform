import { Activity, AlertTriangle, Check, FileText, Users } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { AdminStats } from "@/lib/backend";

const ICONS = {
  total: Activity,
  blocked: AlertTriangle,
  allowed: Check,
  evidence: FileText,
  users: Users,
} as const;

export function StatsCards({ stats }: { stats: AdminStats }) {
  const items = [
    { key: "total", label: "Total Queries", value: stats.total_queries, sub: `${stats.medical_queries} medical` },
    { key: "allowed", label: "Allowed", value: stats.allowed_queries, sub: `${pct(stats.allowed_queries, stats.total_queries)}%` },
    { key: "blocked", label: "Blocked", value: stats.blocked_queries, sub: `${pct(stats.blocked_queries, stats.total_queries)}%` },
    { key: "evidence", label: "Evidence Rows", value: stats.total_evidence_rows, sub: "tool outputs collected" },
    { key: "users", label: "Unique Users", value: stats.unique_users, sub: `${stats.queries_with_errors} errored` },
  ] as const;

  return (
    <div className="grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-5">
      {items.map((item) => {
        const Icon = ICONS[item.key];
        return (
          <Card key={item.key}>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-xs font-medium text-muted-foreground">{item.label}</CardTitle>
              <Icon className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-semibold">{item.value.toLocaleString()}</div>
              <p className="text-xs text-muted-foreground">{item.sub}</p>
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}

function pct(part: number, total: number): number {
  if (total === 0) return 0;
  return Math.round((part / total) * 100);
}
