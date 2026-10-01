"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState, type ComponentProps } from "react";

import { localLoginHref } from "@/features/security/login-navigation";

export function LoginReturnLink(props: Omit<ComponentProps<typeof Link>, "href">) {
  const pathname = usePathname();
  const [loginHref, setLoginHref] = useState("/login");

  useEffect(() => {
    let active = true;
    const update = () => {
      void Promise.resolve().then(() => {
        if (!active) return;
        const location = window.location;
        setLoginHref(localLoginHref(`${location.pathname}${location.search}${location.hash}`));
      });
    };
    update();
    window.addEventListener("popstate", update);
    window.addEventListener("hashchange", update);
    return () => {
      active = false;
      window.removeEventListener("popstate", update);
      window.removeEventListener("hashchange", update);
    };
  }, [pathname]);

  return <Link {...props} href={loginHref} />;
}
