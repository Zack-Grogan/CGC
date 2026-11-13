# Queue reliability and scale-to-zero operation

CGC keeps the job ledger on the local host. Beam runs a submitted generation task. No always-on server or GPU is required.

## Resource policy

The resident worker configuration sets `min_containers=0`, `max_containers=1`, one worker, and `retries=0`. A finite idle window permits consecutive jobs to reuse loaded weights. The current default is 60 seconds. `cgc queue configure --keep-warm-seconds 0` permits immediate idle scale-down; a value up to 3600 permits a longer review window. `cgc queue cool` explicitly releases a retained GPU worker.

The owner specified a workspace limit of five concurrent GPU containers on 2026-11-12. The current CGC controller serializes GPU jobs and retains at most one CGC GPU allocation, so it stays below that ceiling. Five is an upper limit, not a minimum. Any future parallel controller must count starting, running, and retained warm GPU containers across profiles against that aggregate limit.

Warm idle time is billable. Setting a minimum of one container would maintain an always-on baseline, so CGC does not do that. These semantics follow Beam's [keep-warm documentation](https://docs.beam.cloud/v2/endpoint/keep-warm) and [autoscaling controls](https://docs.beam.cloud/v2/scaling/concurrency).

The queue groups up to 20 jobs or 600 seconds of work for a model before checking older backlog priority. It does not select prompts or evaluate artistic quality. Codex decides which files to submit next.

## Input admission and transfer

Admission reserves the output path in SQLite and snapshots each explicit input by SHA-256. A cached snapshot is checked again before reuse. A snapshot changed after admission is rejected before upload. Snapshot creation retains a 256 MiB free-space reserve for queue state and recovery.

Inputs are uploaded to the private `cgc-inputs` volume. Task messages contain names, sizes, and hashes. A 17 MiB provider simulation confirmed that the controller sends a descriptor smaller than 1 KiB and skips the second upload when the same content is already present. This is separate from the earlier live large-asset qualification in the enhancement acceptance record.

Workers copy input files into job-local temporary storage and check their sizes and hashes before processing. The [Beam volume API](https://docs.beam.cloud/v2/data/volume) supplies persistent file storage; CGC uses the official CLI for uploads and downloads.

## Submission and restart

The controller records the request identity before the submission call. After Beam returns the task ID, it commits that ID atomically. A known task is polled and collected after restart. It is not submitted again. Beam documents this task-ID and polling pattern in [Running Async Tasks](https://docs.beam.cloud/v2/task-queue/running-tasks).

The GPU ownership check distinguishes recovery of that same active task from a new task. Recovery can resume polling its own running task. A different task is blocked while the previous paid outcome remains active or uncertain. If the host stopped between the task record and the GPU lease record, recovery reconstructs the lease from the known task ID.

An interrupted submission with no confirmed task ID remains an unknown outcome. CGC refuses an automatic retry. A confirmed input-preparation rejection can be retried explicitly. Automatic provider retries remain disabled because Beam otherwise has its own retry behavior. See [Timeouts and Retries](https://docs.beam.cloud/v2/topics/timeouts-and-retries).

## Collection and job controls

GPU and CPU controllers hold a per-output lock. Manual collection cannot race another collector into a second submission. Main files and sidecars are verified, staged beside their destination, and linked into place atomically. Existing bytes with a different digest are retained and reported as a collision. Provider tracking records and the final report use atomic replacement.

A completed provider task can expose `result.json` before all referenced files are available for download. Collection uses the official Beam CLI and permits four download attempts per artifact. Transfer failures use delays of 1, 2, and 4 seconds. Each CLI call has a maximum timeout of 180 seconds. All downloads share a 600-second collection time budget; the remaining budget can reduce a call timeout. These retries read the existing result volume. They do not submit another inference task or enable provider inference retries.

CGC removes partial download files before another attempt. It downloads and verifies the main file and all listed sidecars before it publishes any new local artifacts. A digest mismatch stops collection immediately; corrupt bytes do not trigger an automatic retry. Invalid manifests and local file collisions also stop collection. Destination staging files are removed if copying or publication fails. Publication is atomic for each file, not a transaction across the complete set; a local failure can leave already verified files for the next collection attempt.

When the retry count or time budget is exhausted, the provider record retains the same task ID, request ID, and `COMPLETE` status. Its `collection.status` is `collection_pending`, with the failure and attempt history. The queue also remains `collection_pending`. Use `cgc jobs collect JOB_ID` to collect that same paid task again after the transfer problem is resolved. Do not submit a replacement generation to recover a completed result.

The Dominion detail run demonstrated this boundary: task `d90a408c-5446-48d5-8ce6-f206ee4359e2` completed once, its first main-file download returned 404 after the manifest was readable, and manual collection retrieved that same task without resubmission. The bounded retry behavior is verified with provider-boundary simulations; this fix did not run another model or allocate a GPU.

Cancellation and new dispatch use the same control lock. A stale database busy flag cannot freeze the queue after a crashed control command. Retry refuses jobs that are queued, running, or recovering. Canceling a completed or already failed local job preserves its actual state.

## Verification

The targeted controller tests execute the real transport controller with a fake Beam boundary. The simulator accepts a paid task, drops the polling connection, then returns RUNNING and COMPLETE during recovery. The test confirms one submission, output collection, and a matching output digest. Separate tests reject another active task, reject a corrupted snapshot, exercise control-lock recovery, reject retry during execution, and verify large-file upload reuse.

Evidence is saved in [controller-verification.txt](../outputs/queue-reliability/controller-verification.txt). These are controller and provider-boundary simulations, not new live model or GPU tests. No cloud resources were created for this audit.

Collection tests additionally simulate a readable manifest followed by a delayed main file and a transient sidecar failure. They verify one paid submission across recovery, exact collected bytes and hashes, finite refusal for persistent transfer failures, immediate refusal for corrupt bytes, preservation of sidecar collisions, and staging cleanup after a local copy failure. The focused evidence and full-suite result (171 tests, one skip) are saved in [collection-verification.txt](../outputs/queue-reliability/collection-verification.txt).

## Practical limits

- The local host must run to dispatch new backlog and collect results. A submitted Beam task can continue while the Mac sleeps.
- A submission interrupted before a task ID is recorded can require provider reconciliation. CGC favors avoiding duplicate paid work.
- The GPU lock is scoped to `CGC_STATE_DIR`. Separate state directories represent separate controllers and can allocate concurrently.
- Output sidecar collisions are reported and preserved. Use distinct output stems for different generations or formats that emit similarly named sidecars.
- CPU processing, imports, or slow file transfers can exceed the chosen warm interval. Scale-down is expected; continuous residency across such gaps is not guaranteed.
- SQLite admission and hashes protect job identity and file integrity. They do not establish artistic quality, correct skin deformation, or engine behavior.
