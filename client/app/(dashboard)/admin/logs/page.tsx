import { AlertTriangle } from "lucide-react";

import { LogsTable } from "@/components/admin/logs-table";
import { Card, CardContent } from "@/components/ui/card";
import { backend } from "@/lib/backend";

export const dynamic = "force-dynamic";

export default async function AdminLogsPage() {
  let logs;
  let error: string | null = null;
  try {
    logs = await backend.auditLogs(200);
  } catch (err) {
    error = String(err);
  }

  return (
    <div className="h-full overflow-y-auto">
      <header className="flex h-14 items-center border-b px-6">
        <div>
          <h1 className="text-sm font-semibold">Audit Logs</h1>
          <p className="text-xs text-muted-foreground">
            Every pipeline run, newest first. Click a row to inspect the full trace.
          </p>
        </div>
      </header>

      <div className="p-6">
        {error ? (
          <Card className="border-destructive/40">
            <CardContent className="flex items-center gap-3 py-4 text-sm">
              <AlertTriangle className="h-4 w-4 text-destructive" />
              <span>Unable to reach backend: {error}</span>
            </CardContent>
          </Card>
        ) : (
          <LogsTable logs={logs || []} />
        )}
      </div>
    </div>
  );
}
