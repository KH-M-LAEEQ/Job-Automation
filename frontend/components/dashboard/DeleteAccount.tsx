"use client";

import { Trash2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { ApiError, apiFetch } from "@/lib/api-client";
import { useAuth } from "@/providers/AuthProvider";

export function DeleteAccount() {
  const { clearSession } = useAuth();
  const router = useRouter();
  const [password, setPassword] = useState("");
  const [confirmText, setConfirmText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  async function handleDelete(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setDeleting(true);
    try {
      await apiFetch("/auth/delete-account", { method: "POST", body: JSON.stringify({ password }) });
      clearSession();
      router.push("/login");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not delete the account");
      setDeleting(false);
    }
  }

  return (
    <Card className="p-6">
      <h2 className="mb-1 text-base font-semibold text-zinc-900 dark:text-zinc-50">Delete account</h2>
      <p className="mb-4 text-sm text-zinc-500 dark:text-zinc-400">
        Permanently deletes your account, uploaded CVs (including the stored files), jobs, applications,
        follow-ups and connected email account. This cannot be undone.
      </p>
      <form onSubmit={handleDelete} className="space-y-3">
        <Field label="Current password">
          <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />
        </Field>
        <Field label='Type "DELETE" to confirm'>
          <Input value={confirmText} onChange={(e) => setConfirmText(e.target.value)} />
        </Field>
        {error && (
          <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-600 dark:bg-red-950/40 dark:text-red-400">{error}</p>
        )}
        <Button type="submit" variant="danger" disabled={deleting || !password || confirmText !== "DELETE"}>
          {deleting ? <Spinner className="h-4 w-4" /> : <Trash2 className="h-4 w-4" />}
          Delete my account
        </Button>
      </form>
    </Card>
  );
}
