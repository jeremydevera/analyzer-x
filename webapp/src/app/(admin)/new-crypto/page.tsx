import type { Metadata } from "next";
import NewCryptoScreen from "@/components/crypto/NewCryptoScreen";

export const metadata: Metadata = {
  title: "New Crypto | Trading Agents",
  description: "Newly listed and announced MEXC coins",
};

export default function NewCryptoPage() {
  return <NewCryptoScreen />;
}
