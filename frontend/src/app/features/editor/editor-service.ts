import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, catchError, throwError } from 'rxjs';

import { environment } from '../../../environments/environment';
import { type EditRecipe, toDocument } from '../../renderer';
import { toApiFailure } from '../../shared/photos/photo-api';

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

@Injectable({ providedIn: 'root' })
export class EditorService {
  private readonly http = inject(HttpClient);

  /**
   * Saves the edit as it stands.
   *
   * <p>The body is the recipe document itself, in the schema's own snake_case
   * form, because that is what is being stored — a wrapper around it would be
   * one more shape the three language models would have to agree about. The
   * server validates it against its own model of the same schema before
   * writing, so a document this client would refuse is refused there too.</p>
   */
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

  saveVersion(projectId: string, recipe: EditRecipe): Observable<SavedVersion> {
    return this.http
      .post<SavedVersion>(
        `${environment.apiBaseUrl}/projects/${projectId}/versions`,
        toDocument(recipe),
      )
      .pipe(catchError((error: unknown) => throwError(() => toApiFailure(error))));
  }
}
