/*
 * Lightweight external LOG sender for the Python distributed log system.
 *
 * Build (Linux/macOS):
 *   gcc log_sender.c -o log_sender -lssl -lcrypto
 *
 * Build (Windows, MinGW/MSYS2):
 *   gcc log_sender.c -o log_sender.exe -lssl -lcrypto -lws2_32
 */

#include <errno.h>
#include <limits.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include <openssl/evp.h>
#include <openssl/hmac.h>

#ifdef _WIN32
#include <winsock2.h>
#include <ws2tcpip.h>
#pragma comment(lib, "Ws2_32.lib")
typedef SOCKET socket_handle;
#define INVALID_SOCKET_HANDLE INVALID_SOCKET
#define close_socket closesocket
#else
#include <arpa/inet.h>
#include <netdb.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <unistd.h>
typedef int socket_handle;
#define INVALID_SOCKET_HANDLE (-1)
#define close_socket close
#endif

#define DEFAULT_HOST "127.0.0.1"
#define DEFAULT_PORT "9000"
#define DEFAULT_NODE_ID "C-EQUIPMENT-01"
#define DEFAULT_MESSAGE "STATUS=NORMAL ACTION=C_CLIENT_HEARTBEAT"
#define DEFAULT_SECRET "my_secret_token"
#define MAX_RESPONSE_SIZE (10U * 1024U * 1024U)

struct options {
    const char *host;
    const char *port;
    const char *node_id;
    const char *message;
    const char *secret;
    int count;
    double interval;
};

static void print_usage(const char *program)
{
    fprintf(stderr,
            "Usage: %s [options]\n"
            "  --host HOST       Producer host (default: %s)\n"
            "  --port PORT       Producer port (default: %s)\n"
            "  --node-id ID      Equipment node ID (default: %s)\n"
            "  --message TEXT    Equipment log message\n"
            "  --count N         Number of logs to send (default: 1)\n"
            "  --interval SEC    Delay between logs (default: 1.0)\n"
            "  --secret SECRET   Shared HMAC secret (default matches config.py)\n"
            "  --help            Show this help\n",
            program, DEFAULT_HOST, DEFAULT_PORT, DEFAULT_NODE_ID);
}

static int parse_positive_int(const char *text, int *result)
{
    char *end = NULL;
    long value;

    errno = 0;
    value = strtol(text, &end, 10);
    if (errno != 0 || end == text || *end != '\0' ||
        value < 1 || value > INT_MAX) {
        return -1;
    }
    *result = (int)value;
    return 0;
}

static int parse_nonnegative_double(const char *text, double *result)
{
    char *end = NULL;
    double value;

    errno = 0;
    value = strtod(text, &end);
    if (errno != 0 || end == text || *end != '\0' ||
        !isfinite(value) || value < 0.0) {
        return -1;
    }
    *result = value;
    return 0;
}

static int parse_args(int argc, char **argv, struct options *opts)
{
    int i;

    for (i = 1; i < argc; ++i) {
        if (strcmp(argv[i], "--help") == 0) {
            print_usage(argv[0]);
            return 1;
        }
        if (i + 1 >= argc) {
            fprintf(stderr, "[C Client] Missing value for %s\n", argv[i]);
            return -1;
        }

        if (strcmp(argv[i], "--host") == 0) {
            opts->host = argv[++i];
        } else if (strcmp(argv[i], "--port") == 0) {
            opts->port = argv[++i];
        } else if (strcmp(argv[i], "--node-id") == 0) {
            opts->node_id = argv[++i];
        } else if (strcmp(argv[i], "--message") == 0) {
            opts->message = argv[++i];
        } else if (strcmp(argv[i], "--secret") == 0) {
            opts->secret = argv[++i];
        } else if (strcmp(argv[i], "--count") == 0) {
            if (parse_positive_int(argv[++i], &opts->count) != 0) {
                fprintf(stderr, "[C Client] --count must be a positive integer\n");
                return -1;
            }
        } else if (strcmp(argv[i], "--interval") == 0) {
            if (parse_nonnegative_double(argv[++i], &opts->interval) != 0) {
                fprintf(stderr, "[C Client] --interval must be non-negative\n");
                return -1;
            }
        } else {
            fprintf(stderr, "[C Client] Unknown option: %s\n", argv[i]);
            return -1;
        }
    }
    return 0;
}

/*
 * Python's canonical_message() uses json.dumps(..., ensure_ascii=True).
 * Equipment IDs and messages are intentionally restricted to ASCII here so
 * escaping is identical without embedding a full Unicode JSON implementation.
 */
static char *json_escape_ascii(const char *input)
{
    const unsigned char *p;
    char *escaped;
    char *out;
    size_t length = 0;

    for (p = (const unsigned char *)input; *p != '\0'; ++p) {
        if (*p >= 0x80) {
            return NULL;
        }
        if (*p == '"' || *p == '\\' || *p == '\b' || *p == '\f' ||
            *p == '\n' || *p == '\r' || *p == '\t') {
            length += 2;
        } else if (*p < 0x20) {
            length += 6;
        } else {
            length += 1;
        }
    }

    escaped = (char *)malloc(length + 1);
    if (escaped == NULL) {
        return NULL;
    }

    out = escaped;
    for (p = (const unsigned char *)input; *p != '\0'; ++p) {
        switch (*p) {
        case '"':  *out++ = '\\'; *out++ = '"'; break;
        case '\\': *out++ = '\\'; *out++ = '\\'; break;
        case '\b': *out++ = '\\'; *out++ = 'b'; break;
        case '\f': *out++ = '\\'; *out++ = 'f'; break;
        case '\n': *out++ = '\\'; *out++ = 'n'; break;
        case '\r': *out++ = '\\'; *out++ = 'r'; break;
        case '\t': *out++ = '\\'; *out++ = 't'; break;
        default:
            if (*p < 0x20) {
                sprintf(out, "\\u%04x", (unsigned int)*p);
                out += 6;
            } else {
                *out++ = (char)*p;
            }
        }
    }
    *out = '\0';
    return escaped;
}

static char *build_canonical_json(const char *message, const char *node_id,
                                  long long timestamp)
{
    static const char *format =
        "{\"message\":\"%s\",\"node_id\":\"%s\",\"sender_id\":\"%s\","
        "\"timestamp\":%lld,\"type\":\"LOG\"}";
    int needed = snprintf(NULL, 0, format, message, node_id, node_id, timestamp);
    char *result;

    if (needed < 0) {
        return NULL;
    }
    result = (char *)malloc((size_t)needed + 1);
    if (result != NULL) {
        snprintf(result, (size_t)needed + 1, format,
                 message, node_id, node_id, timestamp);
    }
    return result;
}

static char *build_signed_json(const char *message, const char *node_id,
                               long long timestamp, const char *signature)
{
    static const char *format =
        "{\"message\":\"%s\",\"node_id\":\"%s\",\"sender_id\":\"%s\","
        "\"signature\":\"%s\",\"timestamp\":%lld,\"type\":\"LOG\"}";
    int needed = snprintf(NULL, 0, format, message, node_id, node_id,
                          signature, timestamp);
    char *result;

    if (needed < 0) {
        return NULL;
    }
    result = (char *)malloc((size_t)needed + 1);
    if (result != NULL) {
        snprintf(result, (size_t)needed + 1, format,
                 message, node_id, node_id, signature, timestamp);
    }
    return result;
}

static int hmac_sha256_hex(const char *secret, const char *data, char output[65])
{
    unsigned char digest[EVP_MAX_MD_SIZE];
    unsigned int digest_length = 0;
    unsigned int i;

    if (HMAC(EVP_sha256(), secret, (int)strlen(secret),
             (const unsigned char *)data, strlen(data),
             digest, &digest_length) == NULL || digest_length != 32) {
        return -1;
    }
    for (i = 0; i < digest_length; ++i) {
        sprintf(output + (i * 2), "%02x", digest[i]);
    }
    output[64] = '\0';
    return 0;
}

static socket_handle connect_to_producer(const char *host, const char *port)
{
    struct addrinfo hints;
    struct addrinfo *addresses = NULL;
    struct addrinfo *address;
    socket_handle sock = INVALID_SOCKET_HANDLE;

    memset(&hints, 0, sizeof(hints));
    hints.ai_family = AF_UNSPEC;
    hints.ai_socktype = SOCK_STREAM;

    if (getaddrinfo(host, port, &hints, &addresses) != 0) {
        return INVALID_SOCKET_HANDLE;
    }
    for (address = addresses; address != NULL; address = address->ai_next) {
        sock = socket(address->ai_family, address->ai_socktype,
                      address->ai_protocol);
        if (sock == INVALID_SOCKET_HANDLE) {
            continue;
        }
        if (connect(sock, address->ai_addr, (int)address->ai_addrlen) == 0) {
            break;
        }
        close_socket(sock);
        sock = INVALID_SOCKET_HANDLE;
    }
    freeaddrinfo(addresses);
    return sock;
}

static int send_all(socket_handle sock, const void *buffer, size_t length)
{
    const char *cursor = (const char *)buffer;

    while (length > 0) {
        int chunk = length > INT_MAX ? INT_MAX : (int)length;
        int sent = send(sock, cursor, chunk, 0);
        if (sent <= 0) {
            return -1;
        }
        cursor += sent;
        length -= (size_t)sent;
    }
    return 0;
}

static int recv_exact(socket_handle sock, void *buffer, size_t length)
{
    char *cursor = (char *)buffer;

    while (length > 0) {
        int chunk = length > INT_MAX ? INT_MAX : (int)length;
        int received = recv(sock, cursor, chunk, 0);
        if (received <= 0) {
            return -1;
        }
        cursor += received;
        length -= (size_t)received;
    }
    return 0;
}

static int send_framed_json(socket_handle sock, const char *json)
{
    size_t payload_length = strlen(json);
    uint32_t network_length;

    if (payload_length > UINT32_MAX) {
        return -1;
    }
    network_length = htonl((uint32_t)payload_length);
    if (send_all(sock, &network_length, sizeof(network_length)) != 0 ||
        send_all(sock, json, payload_length) != 0) {
        return -1;
    }
    return 0;
}

static char *recv_framed_json(socket_handle sock)
{
    uint32_t network_length;
    uint32_t payload_length;
    char *payload;

    if (recv_exact(sock, &network_length, sizeof(network_length)) != 0) {
        return NULL;
    }
    payload_length = ntohl(network_length);
    if (payload_length > MAX_RESPONSE_SIZE) {
        fprintf(stderr, "[C Client] Response exceeds 10 MiB limit\n");
        return NULL;
    }
    payload = (char *)malloc((size_t)payload_length + 1);
    if (payload == NULL) {
        return NULL;
    }
    if (recv_exact(sock, payload, payload_length) != 0) {
        free(payload);
        return NULL;
    }
    payload[payload_length] = '\0';
    return payload;
}

static void sleep_seconds(double seconds)
{
#ifdef _WIN32
    Sleep((DWORD)(seconds * 1000.0));
#else
    struct timespec delay;
    delay.tv_sec = (time_t)seconds;
    delay.tv_nsec = (long)((seconds - (double)delay.tv_sec) * 1000000000.0);
    nanosleep(&delay, NULL);
#endif
}

static int send_one_log(const struct options *opts, int sequence)
{
    long long timestamp = (long long)time(NULL);
    char signature[65];
    char *escaped_message = NULL;
    char *escaped_node_id = NULL;
    char *canonical = NULL;
    char *payload = NULL;
    char *response = NULL;
    socket_handle sock = INVALID_SOCKET_HANDLE;
    int result = -1;

    escaped_message = json_escape_ascii(opts->message);
    escaped_node_id = json_escape_ascii(opts->node_id);
    if (escaped_message == NULL || escaped_node_id == NULL) {
        fprintf(stderr,
                "[C Client] node ID and message must be ASCII and fit in memory\n");
        goto cleanup;
    }

    canonical = build_canonical_json(escaped_message, escaped_node_id, timestamp);
    if (canonical == NULL ||
        hmac_sha256_hex(opts->secret, canonical, signature) != 0) {
        fprintf(stderr, "[C Client] Failed to create HMAC-SHA256 signature\n");
        goto cleanup;
    }
    payload = build_signed_json(escaped_message, escaped_node_id,
                                timestamp, signature);
    if (payload == NULL) {
        fprintf(stderr, "[C Client] Failed to build JSON payload\n");
        goto cleanup;
    }

    printf("[C Client] Connecting to %s:%s for log %d/%d\n",
           opts->host, opts->port, sequence, opts->count);
    sock = connect_to_producer(opts->host, opts->port);
    if (sock == INVALID_SOCKET_HANDLE) {
        fprintf(stderr, "[C Client] Failed to connect to producer\n");
        goto cleanup;
    }
    if (send_framed_json(sock, payload) != 0) {
        fprintf(stderr, "[C Client] Failed to send length-prefixed LOG message\n");
        goto cleanup;
    }
    printf("[C Client] Sent signed LOG from %s (%zu JSON bytes)\n",
           opts->node_id, strlen(payload));

    response = recv_framed_json(sock);
    if (response == NULL) {
        fprintf(stderr, "[C Client] Failed to read producer response\n");
        goto cleanup;
    }
    printf("[C Client] Producer response: %s\n", response);
    result = 0;

cleanup:
    if (sock != INVALID_SOCKET_HANDLE) {
        close_socket(sock);
    }
    free(response);
    free(payload);
    free(canonical);
    free(escaped_node_id);
    free(escaped_message);
    return result;
}

int main(int argc, char **argv)
{
    struct options opts = {
        DEFAULT_HOST,
        DEFAULT_PORT,
        DEFAULT_NODE_ID,
        DEFAULT_MESSAGE,
        DEFAULT_SECRET,
        1,
        1.0
    };
    int parse_result;
    int sequence;
    int failures = 0;

    parse_result = parse_args(argc, argv, &opts);
    if (parse_result != 0) {
        return parse_result > 0 ? EXIT_SUCCESS : EXIT_FAILURE;
    }

#ifdef _WIN32
    {
        WSADATA winsock_data;
        if (WSAStartup(MAKEWORD(2, 2), &winsock_data) != 0) {
            fprintf(stderr, "[C Client] WSAStartup failed\n");
            return EXIT_FAILURE;
        }
    }
#endif

    for (sequence = 1; sequence <= opts.count; ++sequence) {
        if (send_one_log(&opts, sequence) != 0) {
            ++failures;
        }
        if (sequence < opts.count) {
            sleep_seconds(opts.interval);
        }
    }

#ifdef _WIN32
    WSACleanup();
#endif

    if (failures != 0) {
        fprintf(stderr, "[C Client] %d of %d LOG messages failed\n",
                failures, opts.count);
        return EXIT_FAILURE;
    }
    printf("[C Client] Completed %d LOG message(s)\n", opts.count);
    return EXIT_SUCCESS;
}
