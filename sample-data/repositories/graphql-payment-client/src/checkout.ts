import { createPayment } from "./paymentClient";

export function checkout(email: string) {
  return createPayment(email);
}
