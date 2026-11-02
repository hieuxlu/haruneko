<script lang="ts">
    // TODO: text-overflow not working
    import { Button, ProgressBar } from 'carbon-components-svelte';
    import TrashCan from 'carbon-icons-svelte/lib/TrashCan.svelte';
    import WarningHexFilled from 'carbon-icons-svelte/lib/WarningHexFilled.svelte';

    import type { DownloadTask } from '../../../engine/DownloadTask';
    import { Status } from '../../../engine/DownloadTask';

    interface Props {
        job: DownloadTask;
        taskerror: DownloadTask;
    };
    let { job, taskerror = $bindable() }: Props  = $props();
    let status: Status = $state(Status.Queued);
    let progress = $state(0);
    let errors: Error[] = $state([]);

    $effect(() => {
        const task = job;
        const refreshStatus = (value: Status) => { status = value; };
        const refreshProgress = (value: number) => { progress = value; };
        const refreshErrors = (value: Error[]) => { errors = [...value]; };
        refreshStatus(task.Status.Value);
        refreshProgress(task.Progress.Value);
        refreshErrors(task.Errors.Value);
        task.Status.Subscribe(refreshStatus);
        task.Progress.Subscribe(refreshProgress);
        task.Errors.Subscribe(refreshErrors);
        return () => {
            task.Status.Unsubscribe(refreshStatus);
            task.Progress.Unsubscribe(refreshProgress);
            task.Errors.Unsubscribe(refreshErrors);
        };
    });

    const StatusIcons: Record<Status, 'active' | 'finished' | 'error'> = {
        [Status.Queued]: undefined,
        [Status.Paused]: undefined,
        [Status.Downloading]: 'active',
        [Status.Processing]: 'active',
        [Status.Failed]: 'error',
        [Status.Completed]: 'finished',
    };
</script>

<div class="task">
    <div class="progress">
        <ProgressBar
            status={StatusIcons[status]}
            size="sm"
            value={status === Status.Processing
                ? 100
                : progress * 100}
        >
            {#snippet labelChildren()}
                <div class="label">
                    {job.Media.Title}
                    {#if errors.length > 0}
                        <Button
                            kind="danger-ghost"
                            size="small"
                            icon={WarningHexFilled}
                            iconDescription={errors[0]?.message || 'error message missing'}
                            on:click={(e) => {
                                taskerror = job;
                                e.stopPropagation();
                            }}
                        />
                    {/if}
                </div>
            {/snippet}
        </ProgressBar>
    </div>
    <div class="action">
        <Button
            kind="ghost"
            size="small"
            icon={TrashCan}
            iconDescription="Delete"
            on:click={(e) => {
                window.HakuNeko.DownloadManager.Dequeue(job);
                e.stopPropagation();
            }}
        />
    </div>
</div>

<style>
    .task {
        display: grid;
        grid-template-columns: 1fr 3em;
        gap: 1em;
        width: 100%;
        padding-left: 4em;
    }

    .label :global(button) {
        min-height: unset;
    }
</style>
