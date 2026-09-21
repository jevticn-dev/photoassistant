import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, catchError, switchMap, throwError } from 'rxjs';

import { environment } from '../../../environments/environment';
import { EditSchemaError } from '../../renderer';

/** One project, as the API returns it. */
export interface Project {
  readonly id: string;
  readonly name: string;
  readonly photoId: string;
  readonly createdAt: string;
  readonly versionCount: number;

  /** True once a suggestion has been taken or skipped for this photograph. */
  readonly hasChoice: boolean;

  /**
   * The recipe the editor opens on — the last saved version, else the chosen
   * suggestion, else null for the photograph unchanged.
   *
   * <p>Unknown rather than typed: what arrives is a document the API passed on
   * without reading, and `parseRecipe` is what turns it into a recipe or
   * refuses it. A declared type here would be a promise nothing checks.</p>
   */
  readonly startingEdit: unknown;
}

/** One saved version, as the server labelled it. */
export interface SavedVersion {
  readonly id: string;
  readonly label: string;
  readonly createdAt: string;
}

/**
 * One entry in a project's history: a saved version and the recipe it saved.
 *
 * <p>The recipe is `unknown` for the same reason `Project.startingEdit` is —
 * what arrives is a document the API passed on without reading, and
 * `parseRecipe` is what turns it into a recipe or refuses it.</p>
 */
export interface VersionEntry extends SavedVersion {
  readonly edit: unknown;
}

/** What the worker wrote once it finished: the file's size and dimensions. */
export interface ExportResult {
  readonly key: string;
  readonly contentType: string;
  readonly width: number;
  readonly height: number;
  readonly bytes: number;
}

/**
 * Where a queued export has got to.
 *
 * <p>Here rather than in the editor because two features now ask for it — the
 * editor, to offer the file it just made, and the project's list of exports.
 * That is the condition `shared/README.md` sets for moving anything into this
 * folder: a second feature actually asking, not a guess that one might.</p>
 */
export interface JobState {
  readonly id: string;
  readonly status: 'pending' | 'running' | 'done' | 'failed';
  readonly createdAt: string;
  readonly updatedAt: string;
  readonly error: string | null;
  readonly result: ExportResult | null;

  /**
   * The recipe this export rendered.
   *
   * <p>`unknown` for the same reason every stored document is: what arrives is
   * JSON the API passed on without reading.</p>
   */
  readonly edit: unknown;
}

/** A failure with a message to show, chosen by what went wrong. */
export interface ApiFailure {
  readonly summaryKey: string;
}

/**
 * The two calls that are about a photograph rather than about one screen.
 *
 * <p>Here rather than in a feature because the suggestion screen and the editor
 * both need them, which is the condition `shared/README.md` sets for moving
 * anything into this folder. Each screen keeps its own service for the calls
 * only it makes.</p>
 */
@Injectable({ providedIn: 'root' })
export class PhotoApi {
  private readonly http = inject(HttpClient);

  project(projectId: string): Observable<Project> {
    return this.http
      .get<Project>(`${environment.apiBaseUrl}/projects/${projectId}`)
      .pipe(catchError((error: unknown) => throwError(() => toApiFailure(error))));
  }

  /**
   * Everything saved for this project, oldest first.
   *
   * <p>Each entry carries its recipe, so opening one is a redraw rather than a
   * request. There is no companion call for going back to a version: restoring
   * one is saving its recipe again, which is the method below (§B118).</p>
   */
  versions(projectId: string): Observable<readonly VersionEntry[]> {
    return this.http
      .get<VersionEntry[]>(`${environment.apiBaseUrl}/projects/${projectId}/versions`)
      .pipe(catchError((error: unknown) => throwError(() => toApiFailure(error))));
  }

  /**
   * Every export asked for on this project, newest first.
   *
   * <p>Read by the editor when it opens, so a finished file is still reachable
   * after a reload, and by the project's own list of exports.</p>
   */
  exports(projectId: string): Observable<readonly JobState[]> {
    return this.http
      .get<JobState[]>(`${environment.apiBaseUrl}/projects/${projectId}/exports`)
      .pipe(catchError((error: unknown) => throwError(() => toApiFailure(error))));
  }

  /**
   * The finished file of one export.
   *
   * <p>Through `HttpClient` rather than by pointing the browser at the URL,
   * because the address needs the bearer token the interceptor attaches and an
   * anchor carries none.</p>
   */
  download(jobId: string): Observable<Blob> {
    return this.http
      .get(`${environment.apiBaseUrl}/jobs/${jobId}/download`, { responseType: 'blob' })
      .pipe(catchError((error: unknown) => throwError(() => toApiFailure(error))));
  }

  /**
   * The working copy, decoded and ready to upload to the GPU.
   *
   * <p>`premultiplyAlpha` and `colorSpaceConversion` are switched off because
   * the renderer requires it: the browser would otherwise be free to apply a
   * colour transform on decode, and the whole point of the golden test is that
   * these pixels are the ones the Python side measured.</p>
   */
  proxy(photoId: string): Observable<ImageBitmap> {
    return this.http
      .get(`${environment.apiBaseUrl}/photos/${photoId}/proxy`, { responseType: 'blob' })
      .pipe(
        // Through HttpClient rather than `fetch`, so the interceptor attaches
        // the token and no second copy of its storage key exists here.
        switchMap((blob) =>
          createImageBitmap(blob, {
            premultiplyAlpha: 'none',
            colorSpaceConversion: 'none',
          }),
        ),
        catchError((error: unknown) => throwError(() => toApiFailure(error))),
      );
  }
}

/**
 * What to tell the person, by what went wrong.
 *
 * <p>One mapping for every screen: the same 401 means the same thing whoever
 * asked, and a second copy would drift the day one of them gains a case.</p>
 */
export function toApiFailure(error: unknown): ApiFailure {
  // A recipe our own service sent that the schema refuses is a defect, not a
  // condition of this photograph. It gets its own key so the difference
  // survives into the log, even though the person sees a message either way.
  if (error instanceof EditSchemaError) {
    return { summaryKey: 'errors.unreadable' };
  }

  if (!(error instanceof HttpErrorResponse)) {
    return { summaryKey: 'errors.unexpected' };
  }

  if (error.status === 404) {
    return { summaryKey: 'errors.missing' };
  }

  if (error.status === 401) {
    return { summaryKey: 'errors.signedOut' };
  }

  // 503 is the ML service being down, which the API reports distinctly so the
  // person is told to retry rather than told nothing was found.
  if (error.status === 503) {
    return { summaryKey: 'errors.unavailable' };
  }

  return {
    summaryKey: error.status === 0 ? 'errors.unreachable' : 'errors.unexpected',
  };
}

/**
 * Hands a downloaded file to the browser.
 *
 * <p>Here because two screens do it and the mechanics are fiddly enough to be
 * worth having once: an anchor cannot carry the bearer token, so the bytes are
 * fetched first and given to the browser as an object URL. That URL is revoked
 * as soon as the click has been dispatched — the browser has the blob by then,
 * and leaving it would hold the whole export in memory for as long as the page
 * is open.</p>
 */
export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');

  anchor.href = url;
  anchor.download = filename;
  anchor.click();

  URL.revokeObjectURL(url);
}
