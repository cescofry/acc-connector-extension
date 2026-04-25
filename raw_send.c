/*
 * raw_send — spoofed UDP responder for ACC discovery validation (Phase 1).
 *
 * Usage: raw_send <server_ip> <server_port> <server_name> <discovery_id> <dest_ip> <dest_port>
 * Build: gcc -O2 -o raw_send raw_send.c
 * Install (Linux): sudo setcap cap_net_raw+ep ./raw_send
 *
 * Sends one ACC discovery response UDP packet with source IP = server_ip so
 * that ACC sees the reply as coming from the remote server rather than localhost.
 * Requires CAP_NET_RAW (Linux) or root (macOS).
 */
#include <locale.h>
#include <wchar.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <unistd.h>
#include <arpa/inet.h>
#include <sys/socket.h>
#include <netinet/in.h>

#define DISCOVERY_PORT 8999
#define MAX_NAME_LEN   255
#define MAX_PAYLOAD    (1 + 1 + MAX_NAME_LEN * 4 + 2 + 2 + 4 + 1)

static uint16_t ip_checksum(const uint8_t *buf, int len) {
    uint32_t sum = 0;
    for (int i = 0; i + 1 < len; i += 2)
        sum += ((uint32_t)buf[i] << 8) | buf[i + 1];
    if (len & 1)
        sum += (uint32_t)buf[len - 1] << 8;
    while (sum >> 16)
        sum = (sum & 0xffff) + (sum >> 16);
    return ~(uint16_t)sum;
}

/*
 * Build ACC discovery response payload.
 * Format: 0xC0 | name_len(u8) | name(utf32-le) | 0x00 0x01 | port(be-u16) | id(le-u32) | 0xFA
 * Returns byte count written into out[].
 */
static int build_payload(const char *name, int port, uint32_t disc_id, uint8_t *out) {
    setlocale(LC_ALL, "");
    wchar_t wname[MAX_NAME_LEN + 1];
    size_t wlen = mbstowcs(wname, name, MAX_NAME_LEN);
    if (wlen == (size_t)-1) wlen = 0;
    if (wlen > MAX_NAME_LEN) wlen = MAX_NAME_LEN;

    int i = 0;
    out[i++] = 0xC0;
    out[i++] = (uint8_t)wlen;
    for (size_t j = 0; j < wlen; j++) {
        uint32_t cp = (uint32_t)wname[j];
        out[i++] =  cp        & 0xff;
        out[i++] = (cp >>  8) & 0xff;
        out[i++] = (cp >> 16) & 0xff;
        out[i++] = (cp >> 24) & 0xff;
    }
    out[i++] = 0x00; out[i++] = 0x01;
    out[i++] = (port >> 8) & 0xff;
    out[i++] =  port       & 0xff;
    out[i++] =  disc_id        & 0xff;
    out[i++] = (disc_id >>  8) & 0xff;
    out[i++] = (disc_id >> 16) & 0xff;
    out[i++] = (disc_id >> 24) & 0xff;
    out[i++] = 0xFA;
    return i;
}

/* Write a big-endian u16 into buf[]. */
static void put_be16(uint8_t *buf, uint16_t v) {
    buf[0] = v >> 8;
    buf[1] = v & 0xff;
}

/* Write a big-endian u32 into buf[]. */
static void put_be32(uint8_t *buf, uint32_t v) {
    buf[0] = (v >> 24) & 0xff;
    buf[1] = (v >> 16) & 0xff;
    buf[2] = (v >>  8) & 0xff;
    buf[3] =  v        & 0xff;
}

int main(int argc, char *argv[]) {
    if (argc != 7) {
        fprintf(stderr,
            "Usage: %s <server_ip> <server_port> <server_name>"
            " <discovery_id> <dest_ip> <dest_port>\n", argv[0]);
        return 1;
    }

    const char *server_ip   = argv[1];
    int         server_port = atoi(argv[2]);
    const char *server_name = argv[3];
    uint32_t    disc_id     = (uint32_t)strtoul(argv[4], NULL, 10);
    const char *dest_ip     = argv[5];
    int         dest_port   = atoi(argv[6]);

    struct in_addr src_addr, dst_addr;
    if (!inet_aton(server_ip, &src_addr)) {
        fprintf(stderr, "bad server_ip: %s\n", server_ip); return 1;
    }
    if (!inet_aton(dest_ip, &dst_addr)) {
        fprintf(stderr, "bad dest_ip: %s\n", dest_ip); return 1;
    }
    uint32_t src = ntohl(src_addr.s_addr);
    uint32_t dst = ntohl(dst_addr.s_addr);

    /* Build ACC payload */
    uint8_t payload[MAX_PAYLOAD];
    int plen = build_payload(server_name, server_port, disc_id, payload);

    int udp_len = 8 + plen;
    int tot_len = 20 + udp_len;

    /* Assemble raw packet: IPv4 header (20 bytes) + UDP header (8 bytes) + payload */
    uint8_t pkt[20 + 8 + MAX_PAYLOAD];
    memset(pkt, 0, sizeof(pkt));

    /* IPv4 header — all fields in network byte order */
    pkt[0]  = 0x45;                        /* version=4, IHL=5 */
    pkt[1]  = 0;                           /* DSCP/ECN */
    put_be16(pkt + 2, (uint16_t)tot_len);  /* total length */
    put_be16(pkt + 4, 0x0000);             /* identification */
    put_be16(pkt + 6, 0x0000);             /* flags + fragment offset */
    pkt[8]  = 64;                          /* TTL */
    pkt[9]  = IPPROTO_UDP;                 /* protocol */
    /* pkt[10..11] = checksum, filled in below */
    put_be32(pkt + 12, src);               /* source IP (spoofed = server IP) */
    put_be32(pkt + 16, dst);               /* destination IP */
    put_be16(pkt + 10, ip_checksum(pkt, 20));

    /* UDP header */
    put_be16(pkt + 20, DISCOVERY_PORT);    /* source port */
    put_be16(pkt + 22, (uint16_t)dest_port); /* destination port */
    put_be16(pkt + 24, (uint16_t)udp_len); /* length */
    put_be16(pkt + 26, 0);                 /* checksum (0 = disabled, valid for IPv4 UDP) */

    /* Payload */
    memcpy(pkt + 28, payload, plen);

    int sock = socket(AF_INET, SOCK_RAW, IPPROTO_RAW);
    if (sock < 0) { perror("socket"); return 1; }

    struct sockaddr_in dest = {0};
    dest.sin_family = AF_INET;
    dest.sin_addr   = dst_addr;
    dest.sin_port   = htons((uint16_t)dest_port);

    ssize_t n = sendto(sock, pkt, tot_len, 0,
                       (struct sockaddr *)&dest, sizeof(dest));
    if (n < 0) { perror("sendto"); close(sock); return 1; }

    close(sock);
    return 0;
}
