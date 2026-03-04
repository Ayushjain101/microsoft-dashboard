"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";

export function useAuth() {
  const [authenticated, setAuthenticated] = useState<boolean | null>(null);

  useEffect(() => {
    api.verify()
      .then(() => setAuthenticated(true))
      .catch(() => {
        setAuthenticated(false);
        window.location.href = "/login";
      });
  }, []);

  return authenticated;
}
