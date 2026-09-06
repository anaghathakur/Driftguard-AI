import { gql } from "graphql-tag";

export function createPayment(email: string) {
  const mutation = gql`
    mutation CreatePayment($email: String!) {
      createPayment(amount: 100, email: $email) { id }
    }
  `;
  return mutation;
}
