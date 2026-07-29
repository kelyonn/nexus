"use client";

import { useEffect } from "react";
import { captureTokenFromUrl } from "@/lib/token";

/** Runs once on first load to pull `?token=` out of the URL (see lib/token.ts). */
export default function TokenBootstrap() {
  useEffect(() => {
    captureTokenFromUrl();
  }, []);
  return null;
}
