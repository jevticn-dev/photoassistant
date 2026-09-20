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
  saveVersion(projectId: string, recipe: EditRecipe): Observable<SavedVersion> {
    return this.http
      .post<SavedVersion>(
        `${environment.apiBaseUrl}/projects/${projectId}/versions`,
        toDocument(recipe),
      )
      .pipe(catchError((error: unknown) => throwError(() => toApiFailure(error))));
  }
}
