import logging
from datetime import UTC, datetime

from cli import create_parser
from client import ClientConfig, try_run_test
from measurement import create_run_directory, save_run


def main() -> None:
    logging.basicConfig(level=logging.DEBUG, format="%(message)s")
    logging.getLogger("matplotlib").setLevel(logging.WARNING)

    args = create_parser().parse_args()

    if args.command == "analyze":
        from comparison import analyze_manifest

        analyze_manifest(args.manifest)
        return

    run_id = args.run_id or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")

    client_config = ClientConfig(
        duration=args.time,
        print_interval=args.print_interval,
        goodput_interval=args.goodput_interval,
        connect_timeout=args.connect_timeout,
        control_timeout=args.control_timeout,
        data_timeout=args.data_timeout,
        algorithm=args.algorithm,
    )

    if args.command == "compare":
        from comparison import run_comparison

        if args.algorithm:
            raise SystemExit("Use --algorithms with compare")

        complete = run_comparison(args, client_config, run_id)

        if not complete:
            raise SystemExit(1)

    elif args.command == "test":
        out = create_run_directory(args.out_dir, run_id, "single-server-tests")
        result = try_run_test(args.host, args.port, client_config, run_id)

        if result is None:
            raise SystemExit(1)

        trace_dir = out / "tcp-traces" / result.metadata.slug()
        save_run(result.metadata, result.samples, trace_dir)


if __name__ == "__main__":
    main()
