import { checkout } from "./checkout";

export function submitOrder(email: string) {
  return checkout(email);
}
