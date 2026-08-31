import { useEffect, useState } from "react";

import { getCurrentUser, signOut, type StaffUser } from "@/dashboard/lib/auth";
import { LoginScreen } from "@/dashboard/components/LoginScreen";
import { DashboardShell } from "@/dashboard/components/DashboardShell";

/** The staff dashboard's root: resolves whether the browser already holds
 * a valid Cognito session (so a reload does not force a fresh login),
 * then renders the login form or the dashboard shell. */
export function DashboardApp() {
  const [user, setUser] = useState<StaffUser | null>(null);
  const [checkingSession, setCheckingSession] = useState(true);

  useEffect(() => {
    getCurrentUser()
      .then(setUser)
      .finally(() => setCheckingSession(false));
  }, []);

  if (checkingSession) return null;

  if (!user) {
    return <LoginScreen onSignedIn={setUser} />;
  }

  return (
    <DashboardShell
      user={user}
      onSignOut={() => {
        signOut();
        setUser(null);
      }}
    />
  );
}
