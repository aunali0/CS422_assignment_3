#include <errno.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <signal.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

#include "controller.skel.h"

#define ALGORITHM "a3_cc"

static volatile sig_atomic_t stopping;

static void stop(int signal_number)
{
    (void)signal_number;
    stopping = 1;
}

static int check_algorithm(bool available)
{
    char actual[16] = {0};
    socklen_t length = sizeof(actual);
    int result = EXIT_FAILURE;
    int fd = socket(AF_INET, SOCK_STREAM | SOCK_CLOEXEC, IPPROTO_TCP);

    if (fd < 0) {
        perror("Create unconnected socket");
        return result;
    }

    int error = setsockopt(fd, IPPROTO_TCP, TCP_CONGESTION,
                          ALGORITHM, sizeof(ALGORITHM));
    if (!available) {
        if (error == 0)
            fprintf(stderr, ALGORITHM " is still selectable after unload\n");
        else if (errno != ENOENT)
            perror("Check algorithm removal");
        else
            result = EXIT_SUCCESS;
        goto cleanup;
    }

    if (error < 0) {
        perror("Select " ALGORITHM);
        goto cleanup;
    }
    if (getsockopt(fd, IPPROTO_TCP, TCP_CONGESTION, actual, &length) < 0) {
        perror("Read selected algorithm");
        goto cleanup;
    }
    if (strcmp(actual, ALGORITHM) != 0) {
        fprintf(stderr, "Expected %s, got %s\n", ALGORITHM, actual);
        goto cleanup;
    }
    result = EXIT_SUCCESS;

cleanup:
    close(fd);
    return result;
}

int main(int argc, char **argv)
{
    struct controller_bpf *controller;
    struct bpf_link *link;
    struct sigaction action = {.sa_handler = stop};
    int result = EXIT_FAILURE;

    if (argc > 2 || (argc == 2 && strcmp(argv[1], "--check") != 0)) {
        fprintf(stderr, "Usage: %s [--check]\n", argv[0]);
        return result;
    }

    sigemptyset(&action.sa_mask);
    if (sigaction(SIGINT, &action, NULL) < 0 ||
        sigaction(SIGTERM, &action, NULL) < 0) {
        perror("Install signal handlers");
        return result;
    }

    controller = controller_bpf__open_and_load();
    if (!controller) {
        perror("Load controller (requires BPF privileges)");
        return result;
    }
    link = bpf_map__attach_struct_ops(controller->maps.a3_cc);
    if (!link) {
        perror("Register " ALGORITHM);
        goto cleanup;
    }

    result = check_algorithm(true);
    if (result == EXIT_SUCCESS) {
        puts("Registered " ALGORITHM "; socket readback passed.");
        if (argc == 1) {
            puts("Press Ctrl+C to unload.");
            fflush(stdout);
            while (!stopping)
                sleep(1);
        }
    }

    int error = bpf_link__destroy(link);
    if (error < 0) {
        fprintf(stderr, "Unload controller: %s\n", strerror(-error));
        result = EXIT_FAILURE;
    }

cleanup:
    controller_bpf__destroy(controller);
    if (result == EXIT_SUCCESS) {
        result = check_algorithm(false);
        if (result == EXIT_SUCCESS)
            puts("Unloaded " ALGORITHM "; algorithm removal check passed.");
    }
    return result;
}
