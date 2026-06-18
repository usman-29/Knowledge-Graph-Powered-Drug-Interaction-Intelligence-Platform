import { AlertTriangle } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { backend } from "@/lib/backend";

export const dynamic = "force-dynamic";

const ROLE_VARIANT: Record<string, "default" | "secondary" | "outline" | "destructive"> = {
  ADMIN: "default",
  CLINICIAN: "secondary",
  PATIENT: "outline",
  GUEST: "outline",
};

export default async function AdminUsersPage() {
  let users;
  let error: string | null = null;
  try {
    users = await backend.listUsers();
  } catch (err) {
    error = String(err);
  }

  return (
    <div className="h-full overflow-y-auto">
      <header className="flex h-14 items-center border-b px-6">
        <div>
          <h1 className="text-sm font-semibold">Users</h1>
          <p className="text-xs text-muted-foreground">
            Registered accounts. All user state lives in the backend SQLite store.
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
        ) : !users || users.length === 0 ? (
          <Card className="p-8 text-center text-sm text-muted-foreground">
            No users registered yet.
          </Card>
        ) : (
          <Card>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Email</TableHead>
                  <TableHead>Role</TableHead>
                  <TableHead>Registered</TableHead>
                  <TableHead>ID</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {users.map((u) => (
                  <TableRow key={u.id}>
                    <TableCell className="font-medium">{u.name || "—"}</TableCell>
                    <TableCell>{u.email}</TableCell>
                    <TableCell>
                      <Badge variant={ROLE_VARIANT[u.role] || "outline"}>{u.role}</Badge>
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {new Date(u.created_at * 1000).toLocaleDateString()}
                    </TableCell>
                    <TableCell className="font-mono text-xs text-muted-foreground">
                      {u.id.slice(0, 8)}
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
