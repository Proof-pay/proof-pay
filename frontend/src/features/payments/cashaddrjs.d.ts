declare module "cashaddrjs" {
  const cashaddr: {
    decode(address: string): { prefix: string; type: string; hash: Uint8Array }
  }
  export default cashaddr
}
