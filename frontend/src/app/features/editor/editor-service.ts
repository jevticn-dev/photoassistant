import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, catchError, throwError, timeout } from 'rxjs';

import { environment } from '../../../environments/environment';
import { type EditRecipe, toDocument } from '../../renderer';
import { type JobState, type SavedVersion, toApiFailure } from '../../shared/photos/photo-api';

/**
 * How long one poll may take before it counts as lost.
 *
 * <p>Generous, because a poll competes for the machine with the render it is
 * asking about: while the worker is going through tens of megapixels, the API,
 * the database and the browser are all on the same processor. This is a floor
 * under a request that will never answer, not a performance budget.</p>
 */
const JOB_POLL_TIMEOUT_MS = 20_000;

@Injectable({ providedIn: 'root' })
export class EditorService {
  private readonly http = inject(HttpClient);

  /**
   * Asks for the photograph at full size with this edit applied.
   *
   * <p>The body is the recipe, exactly as saving a version takes it: what is
   * exported is what is on screen. Nothing comes back but the id of the job to
   * follow — a full-resolution render is seconds of work and happens in the ML
   * service, not in this request (ADR-7).</p>
   */
  requestExport(projectId: string, recipe: EditRecipe): Observable<{ jobId: string }> {
    return this.http
      .post<{ jobId: string }>(
        `${environment.apiBaseUrl}/projects/${projectId}/export`,
        toDocument(recipe),
      )
      .pipe(catchError((error: unknown) => throwError(() => toApiFailure(error))));
  }

  /** Where a job has got to. The editor asks this until it stops being pending. */
  job(jobId: string): Observable<JobState> {
    return this.http.get<JobState>(`${environment.apiBaseUrl}/jobs/${jobId}`).pipe(
      // Inside this pipe rather than at the caller, and that placement is the
      // point: everything that leaves this method has to be an ApiFailure, and
      // a TimeoutError raised outside it would arrive as something with no
      // message to show — which is a failure that reaches the person as a blank
      // screen rather than as a sentence.
      timeout(JOB_POLL_TIMEOUT_MS),
      catchError((error: unknown) => throwError(() => toApiFailure(error))),
    );
  }

  /**
   * Saves the edit as it stands.
   *
   * <p>The body is the recipe document itself, in the schema's own snake_case
   * form, because that is what is being stored — a wrapper around it would be
   * one more shape the three language models would have to agree about. The
   * server validates it against its own model of the same schema before
   * writing, so a document this client would refuse is refused there too.</p>
   */
  saveVersion(projectId: string, recipe: EditRecipe): Observable<SavedVersion> {
    return this.http
      .post<SavedVersion>(
        `${environment.apiBaseUrl}/projects/${projectId}/versions`,
        toDocument(recipe),
      )
      .pipe(catchError((error: unknown) => throwError(() => toApiFailure(error))));
  }
}
