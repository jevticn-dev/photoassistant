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
