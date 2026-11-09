"""Sequential clustering jobs with incremental publication and cooperative cancellation."""

from copy import deepcopy
from pathlib import Path

from qtpy import QtCore

from ..data.projectdata import ClusteringResult
from .analysisworker import AnalysisTask
from .clusteringmethods import clustering_method
from .segmentationio import clustering_relative_path, save_xrf_sample


class ClusteringBatchWorker(AnalysisTask):
    """Read and cluster one sample at a time; save before announcing completion."""

    sample_started = QtCore.Signal(int, object)
    work_progress = QtCore.Signal(int, int, str)
    sample_finished = QtCore.Signal(object)
    sample_failed = QtCore.Signal(object, str)

    def __init__(self, jobs, sources, method_id, parameters, project_dir):
        super().__init__()
        self.jobs = tuple(jobs)
        self.sources = dict(sources)
        self.method_id = method_id
        self.parameters = deepcopy(parameters)
        self.project_dir = Path(project_dir)

    def compute(self):
        completed = []
        method = clustering_method(self.method_id)
        total_work = sum(len(job.refs) + 1 for job in self.jobs)
        completed_work = 0
        for index, job in enumerate(self.jobs):
            self.report(f"Clustering {job.sample_name}")
            self.sample_started.emit(index, job)
            try:

                def progress(done, total, element, job=job, offset=completed_work):
                    self.report(f"{job.sample_name}: {element}")
                    work = offset + round(len(job.refs) * done / max(1, total))
                    self.work_progress.emit(work, total_work, f"{job.sample_name}: {element}")

                progress(0, len(job.refs), "Loading maps")
                arrays = [self.sources[ref.source_id].load_array(ref) for ref in job.refs]
                output = method.compute(
                    arrays, job, self.parameters, self.report, progress=progress
                )
                self.report(f"Saving {job.sample_name}")
                self.work_progress.emit(
                    completed_work + len(job.refs), total_work, f"{job.sample_name}: Saving"
                )
                save_xrf_sample(
                    output,
                    self.project_dir / clustering_relative_path(job.sample_id, self.method_id),
                    method_id=self.method_id,
                )
                self.report(f"Completed {job.sample_name}")
                self.sample_finished.emit(
                    ClusteringResult(
                        job.sample_id,
                        job.refs,
                        deepcopy(self.parameters),
                        output,
                        method_id=self.method_id,
                        sidecar=str(clustering_relative_path(job.sample_id, self.method_id)),
                    )
                )
                completed.append(job.sample_id)
            except InterruptedError:
                raise
            except Exception as exc:
                self.sample_failed.emit(job, str(exc))
            completed_work += len(job.refs) + 1
            self.work_progress.emit(completed_work, total_work, job.sample_name)
        return completed
