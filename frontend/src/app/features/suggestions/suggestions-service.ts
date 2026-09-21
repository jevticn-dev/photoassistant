import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, catchError, map, throwError } from 'rxjs';

import { environment } from '../../../environments/environment';
import { type EditRecipe, parseRecipe } from '../../renderer';
import { PhotoApi, type Project, toApiFailure } from '../../shared/photos/photo-api';

export type { ApiFailure as SuggestionsFailure, Project } from '../../shared/photos/photo-api';

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

@Injectable({ providedIn: 'root' })
export class SuggestionsService {
  private readonly http = inject(HttpClient);
  private readonly api = inject(PhotoApi);

  /**
   * The project and the working copy are the same two calls the editor makes,
   * so they live in `shared/` and this passes them through rather than
   * reaching across into another feature for them.
   */
  project(projectId: string): Observable<Project> {
    return this.api.project(projectId);
  }

  proxy(photoId: string): Observable<ImageBitmap> {
    return this.api.proxy(photoId);
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
        catchError((error: unknown) => throwError(() => toApiFailure(error))),
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
      .pipe(catchError((error: unknown) => throwError(() => toApiFailure(error))));
  }
}
