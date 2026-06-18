import Link from "next/link";
import { AlertTriangle, ChevronRight, Pill } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { backend } from "@/lib/backend";

export const dynamic = "force-dynamic";

export default async function PatientsPage() {
  let patients;
  let error: string | null = null;
  try {
    patients = await backend.listPatients();
  } catch (err) {
    error = String(err);
  }

  return (
    <div className="h-full overflow-y-auto">
      <header className="flex h-14 items-center border-b px-6">
        <div>
          <h1 className="text-sm font-semibold">Patient Roster</h1>
          <p className="text-xs text-muted-foreground">
            Select a patient to open a chat scoped to their current medications.
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
        ) : !patients || patients.length === 0 ? (
          <Card className="p-8 text-center text-sm text-muted-foreground">
            No patients available.
          </Card>
        ) : (
          <Card>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>ID</TableHead>
                  <TableHead>Alias</TableHead>
                  <TableHead>Age / Sex</TableHead>
                  <TableHead>Primary Condition</TableHead>
                  <TableHead>Medications</TableHead>
                  <TableHead className="w-8" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {patients.map((p) => (
                  <TableRow key={p.id}>
                    <TableCell>
                      <Link href={`/patients/${p.id}`} className="font-mono text-xs hover:underline">
                        {p.id}
                      </Link>
                    </TableCell>
                    <TableCell>
                      <Link href={`/patients/${p.id}`} className="font-medium hover:underline">
                        {p.display_name}
                      </Link>
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {p.age} · {p.sex}
                    </TableCell>
                    <TableCell className="text-sm">
                      {p.primary_condition || <span className="text-muted-foreground">—</span>}
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline" className="gap-1">
                        <Pill className="h-3 w-3" />
                        {p.medication_count}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <Link href={`/patients/${p.id}`}>
                        <ChevronRight className="h-4 w-4 text-muted-foreground" />
                      </Link>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Card>
        )}
      </div>
    </div>
  );
}
