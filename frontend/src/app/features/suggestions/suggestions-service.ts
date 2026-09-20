import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, catchError, map, switchMap, throwError } from 'rxjs';

import { environment } from '../../../environments/environment';
import { EditSchemaError, type EditRecipe, parseRecipe } from '../../renderer';

/** One project, as the API returns it. */
export interface Project {
  readonly id: string;
  readonly name: string;
  readonly photoId: string;
  readonly createdAt: string;
  readonly versionCount: number;
  /** True once a suggestion has been taken or skipped for this photograph. */
  readonly hasChoice: boolean;
}

/** One suggestion, as it arrives — no image (phase 4, decision C). */
export interface SuggestionDto {
  readonly recipe: unknown;
  readonly sourceReference: string;
  readonly expert: string | null;
  readonly sceneDistance: number;
}

export interface SuggestionsResponse {
  readonly suggestions: readonly SuggestionDto[];
  readonly poolSize: number;
}

/** A suggestion with its recipe parsed and ready for the renderer. */
export interface ParsedSuggestion {
  readonly index: number;
  readonly recipe: EditRecipe;
  readonly raw: SuggestionDto;
}

export interface SuggestionsFailure {
  readonly summaryKey: string;
}

@Injectable({ providedIn: 'root' })
export class SuggestionsService {
  private readonly http = inject(HttpClient);

  project(projectId: string): Observable<Project> {
    return this.http
      .get<Project>(`${environment.apiBaseUrl}/projects/${projectId}`)
      .pipe(catchError((error: unknown) => throwError(() => toFailure(error))));
  }

  /**
   * The three suggestions for a photograph.
   *
   * <p>Recipes are parsed here rather than in the screen. `parseRecipe` is the
   * schema's own validator, shared with the renderer, so a document the editor
   * could not apply is refused at the boundary instead of failing later inside
   * a shader.</p>
   */
  suggestions(photoId: string): Observable<readonly ParsedSuggestion[]> {
    return this.http
      .post<SuggestionsResponse>(
        `${environment.apiBaseUrl}/photos/${photoId}/recommendations`,
        null,
      )
      .pipe(
        map((body) =>
          body.suggestions.map((raw, index) => ({
            index,
            recipe: parseRecipe(raw.recipe),
            raw,
          })),
        ),
        catchError((error: unknown) => throwError(() => toFailure(error))),
      );
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
        catchError((error: unknown) => throwError(() => toFailure(error))),
      );
  }

  /** Records what was shown and what was taken. Index null means none of them. */
  recordChoice(
    photoId: string,
    shown: readonly SuggestionDto[],
    chosenIndex: number | null,
  ): Observable<void> {
    return this.http
      .post<void>(`${environment.apiBaseUrl}/photos/${photoId}/choices`, {
        shown,
        chosenIndex,
      })
      .pipe(catchError((error: unknown) => throwError(() => toFailure(error))));
  }
}

function toFailure(error: unknown): SuggestionsFailure {
  // A recipe our own service sent that the schema refuses is a defect, not a
  // condition of this photograph. It gets its own key so the difference
  // survives into the log, even though the person sees a message either way.
  if (error instanceof EditSchemaError) {
    return { summaryKey: 'suggestions.errors.unreadable' };
  }

  if (!(error instanceof HttpErrorResponse)) {
    return { summaryKey: 'suggestions.errors.unexpected' };
  }

  if (error.status === 404) {
    return { summaryKey: 'suggestions.errors.missing' };
  }

  if (error.status === 401) {
    return { summaryKey: 'suggestions.errors.signedOut' };
  }

  // 503 is the ML service being down, which the API reports distinctly so the
  // person is told to retry rather than told nothing was found.
  if (error.status === 503) {
    return { summaryKey: 'suggestions.errors.unavailable' };
  }

  return {
    summaryKey:
      error.status === 0 ? 'suggestions.errors.unreachable' : 'suggestions.errors.unexpected',
  };
}
