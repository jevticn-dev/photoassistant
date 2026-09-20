import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { vi } from 'vitest';

import { environment } from '../../../../environments/environment';
import { provideTranslations } from '../../../core/i18n/translation.config';
import { ProjectThumbnail } from './project-thumbnail';

const PHOTO = '0199a1f0-0000-7000-8000-00000000000a';

describe('ProjectThumbnail', () => {
  let fixture: ComponentFixture<ProjectThumbnail>;
  let http: HttpTestingController;
  let created: string[];
  let revoked: string[];

  beforeEach(async () => {
    created = [];
    revoked = [];

    // jsdom has neither of these. Recording them is the point: what this
    // component exists to get right is the pairing.
    URL.createObjectURL = vi.fn(() => {
      const url = `blob:${created.length}`;
      created.push(url);

      return url;
    });
    URL.revokeObjectURL = vi.fn((url: string) => void revoked.push(url));

    await TestBed.configureTestingModule({
      imports: [ProjectThumbnail],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideTranslations()],
    }).compileComponents();

    fixture = TestBed.createComponent(ProjectThumbnail);
    http = TestBed.inject(HttpTestingController);
    fixture.componentRef.setInput('photoId', PHOTO);
    fixture.detectChanges();
  });

  afterEach(() => {
    http.match((request) => request.url.includes('/i18n/')).forEach((r) => r.flush({}));
    TestBed.resetTestingModule();
  });

  function answer(): void {
    http
      .expectOne(`${environment.apiBaseUrl}/photos/${PHOTO}/thumbnail`)
      .flush(new Blob(['pixels']));
    fixture.detectChanges();
  }

  it('asks through HttpClient, so the token is attached to the request', () => {
    // The reason this is not an <img src>: the interceptor only sees requests
    // that go through HttpClient, and the route needs the bearer token.
    http.expectOne(`${environment.apiBaseUrl}/photos/${PHOTO}/thumbnail`);
  });

  it('shows the picture once the bytes arrive', () => {
    answer();

    expect((fixture.nativeElement as HTMLElement).querySelector('img')?.getAttribute('src')).toBe(
      'blob:0',
    );
  });

  it('releases the address when the card goes away', () => {
    // An object URL is a reference nothing collects: the browser cannot know
    // the page has stopped referring to it. A list of them is the leak the
    // phase wrote down as a trap.
    answer();
    fixture.destroy();

    expect(revoked).toEqual(['blob:0']);
  });

  it('a photograph that will not load leaves the card usable', () => {
    // The project can still be opened, renamed and deleted; taking the list
    // down over one missing derivative would lose the ones that arrived.
    http.expectOne(`${environment.apiBaseUrl}/photos/${PHOTO}/thumbnail`).flush(null, {
      status: 404,
      statusText: 'Not Found',
    });
    fixture.detectChanges();

    const element = fixture.nativeElement as HTMLElement;

    expect(element.querySelector('img')).toBeNull();
    expect(element.querySelector('.thumbnail__blank')).not.toBeNull();
  });
});
