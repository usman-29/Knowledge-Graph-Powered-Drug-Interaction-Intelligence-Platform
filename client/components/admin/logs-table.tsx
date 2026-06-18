"use client";
import { useState } from "react";
import { ChevronRight } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Separator } from "@/components/ui/separator";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { AuditLogEntry } from "@/lib/backend";
import { formatRelativeTime } from "@/lib/utils";

export function LogsTable({ logs }: { logs: AuditLogEntry[] }) {
  const [selected, setSelected] = useState<AuditLogEntry | null>(null);

  if (logs.length === 0) {
    return (
      <Card className="p-8 text-center text-sm text-muted-foreground">
        No audit log entries yet. Send a query from the chat page to create one.
      </Card>
    );
  }

  return (
    <>
      <Card>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Time</TableHead>
              <TableHead>User</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Input</TableHead>
              <TableHead>Output</TableHead>
              <TableHead>Drugs</TableHead>
              <TableHead>Evidence</TableHead>
              <TableHead className="w-8" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {logs.map((log) => (
              <TableRow
                key={log.trace_id}
                onClick={() => setSelected(log)}
                className="cursor-pointer"
              >
                <TableCell className="font-mono text-xs">{formatRelativeTime(log.timestamp)}</TableCell>
                <TableCell className="text-xs">{log.user_id || "—"}</TableCell>
                <TableCell>
                  {log.blocked ? (
                    <Badge variant="destructive">Blocked</Badge>
                  ) : (
                    <Badge variant="success">Allowed</Badge>
                  )}
                </TableCell>
                <TableCell>
                  <FlagBadge flag={log.input_security_flag} />
                </TableCell>
                <TableCell>
                  <FlagBadge flag={log.output_security_flag} />
                </TableCell>
                <TableCell className="text-xs">
                  {log.drugs_identified.length === 0
                    ? "—"
                    : log.drugs_identified.slice(0, 2).join(", ") + (log.drugs_identified.length > 2 ? "…" : "")}
                </TableCell>
                <TableCell className="text-xs tabular-nums">{log.evidence_count}</TableCell>
                <TableCell>
                  <ChevronRight className="h-4 w-4 text-muted-foreground" />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Card>

      <Dialog open={!!selected} onOpenChange={(o) => !o && setSelected(null)}>
        <DialogContent>
          {selected ? <LogDetails log={selected} /> : null}
        </DialogContent>
      </Dialog>
    </>
  );
}

function FlagBadge({ flag }: { flag: string | null | undefined }) {
  if (!flag) return <span className="text-xs text-muted-foreground">—</span>;
  const isClean = flag === "CLEAN";
  return (
    <Badge variant={isClean ? "outline" : "warning"} className="text-[10px] font-mono">
      {flag}
    </Badge>
  );
}

type TraceStep = Record<string, unknown> & {
  agent?: string;
  node?: string;
  summary?: string;
  error?: string | null;
};

function LogDetails({ log }: { log: AuditLogEntry }) {
  const trace: TraceStep[] = log.pipeline_trace || (log.trail as TraceStep[] | undefined) || [];

  return (
    <>
      <DialogHeader>
        <DialogTitle>Trace {log.trace_id.slice(0, 8)}</DialogTitle>
        <DialogDescription>
          {new Date(log.timestamp).toLocaleString()} · user={log.user_id || "anonymous"}
        </DialogDescription>
      </DialogHeader>

      <div className="space-y-4">
        <section>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">Status</h3>
          <div className="flex flex-wrap gap-2">
            {log.blocked ? <Badge variant="destructive">Blocked</Badge> : <Badge variant="success">Allowed</Badge>}
            {log.is_medical ? <Badge variant="outline">Medical</Badge> : null}
            <Badge variant="outline">Input: {log.input_security_flag || "—"}</Badge>
            <Badge variant="outline">Output: {log.output_security_flag || "—"}</Badge>
          </div>
          {log.block_reason ? (
            <p className="mt-2 rounded-md bg-muted p-2 text-xs">{log.block_reason}</p>
          ) : null}
        </section>

        <Separator />

        <section>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Pipeline Trace
          </h3>
          <div className="space-y-1.5">
            {trace.length === 0 ? (
              <p className="text-xs text-muted-foreground">No trace entries.</p>
            ) : (
              trace.map((step, i) => (
                <div key={i} className="rounded-md border border-border p-2 text-xs">
                  <div className="flex items-center justify-between">
                    <div className="font-mono font-medium">
                      {step.agent || step.node || "node"}
                    </div>
                    {step.error ? (
                      <Badge variant="destructive" className="text-[10px]">
                        error
                      </Badge>
                    ) : null}
                  </div>
                  {step.summary ? (
                    <div className="mt-1 text-muted-foreground">{step.summary}</div>
                  ) : null}
                  {step.error ? (
                    <div className="mt-1 font-mono text-destructive">{step.error}</div>
                  ) : null}
                </div>
              ))
            )}
          </div>
        </section>

        {log.final_answer ? (
          <>
            <Separator />
            <section>
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Final Answer
              </h3>
              <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded-md bg-muted p-3 text-xs">
                {log.final_answer}
              </pre>
            </section>
          </>
        ) : null}
      </div>
    </>
  );
}
