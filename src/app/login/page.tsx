import { LoginForm } from "@/components/security/login-form";
import { safeLocalReturnTo } from "@/features/security/login-navigation";

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;
  return <LoginForm returnTo={safeLocalReturnTo(params.returnTo)} />;
}
