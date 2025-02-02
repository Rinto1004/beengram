from django.contrib.auth import get_user_model, login
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.sites.shortcuts import get_current_site
from django.core import signing
from django.db.models import Case, Count, Q, When
from django.http import (
    HttpResponseBadRequest,
    HttpResponseRedirect,
    JsonResponse,
)
from django.shortcuts import get_object_or_404
from django.template.loader import render_to_string
from django.urls import reverse_lazy
from django.views.generic.base import RedirectView, View
from django.views.generic.detail import DetailView
from django.views.generic.edit import CreateView, DeleteView, UpdateView
from django.views.generic.list import ListView
from .forms import (
    ConfirmForm,
    PostForm,
    ProfileEditForm,
    SearchForm,
    SignUpForm,
    CommentForm,
)
from .models import Post,Comment
import PIL, os, io
from django.core.files.uploadedfile import InMemoryUploadedFile



User = get_user_model()


class PostListView(LoginRequiredMixin, ListView):
    model = Post
    ordering = ("-post_date",)
    paginate_by = 20

    def get_queryset(self):
        queryset = super().get_queryset().select_related("user")
        if "follow" in self.request.GET:
            queryset = queryset.filter(
                Q(user=self.request.user)
                | Q(user__in=self.request.user.follow.all())
            )
        return queryset


class SignUpView(CreateView):
    template_name = "registration/signup.html"
    success_url = reverse_lazy("signup_email_send")
    form_class = SignUpForm
    
    def form_valid(self, form):
        user = form.save(commit=False)
        user.is_active = False
        user.save()
        self.object = user

        current_site = get_current_site(self.request)
        context = {
            "protocol": self.request.scheme,
            "domain": current_site.domain,
            "token": signing.dumps(user.pk),
            "user": user,
        }
        subject = "[BeEngram]アカウントを有効化してください"
        message = render_to_string(
            "registration/email/signup_message.txt", context
        )
        user.email_user(subject, message)
        return HttpResponseRedirect(self.get_success_url())



class ActivateView(RedirectView):
    max_age = 60*60*24
    error_messages = {
        "Invalid": "不正なURLです。",
        "expire": "URLの有効期限が切れています。",
        "user": "このユーザーはすでに削除されたか存在しません。",
        "active": "ユーザー%(name)%はすでに有効化されています。",
    }
    def get(self, request, *args, **kwargs):
        token = self.kwargs["token"]
        max_age = 60*60*24
        try:
            user_pk = signing.loads(token, max_age)
        except signing.BadSignature:
            return HttpResponseBadRequest(self.error_messages["invalid"])
        except signing.SignatureExpired:
            return HttpResponseBadRequest(self.error_messages["expire"])
        
        try:
            user = User.objects.get(pk=user_pk)
        except User.DoesNotExist:
            return HttpResponseBadRequest(self.error_messages["expire"])
        
        if user.is_active:
            return HttpResponseBadRequest(
                self.error_messages["active"] % {"name": user.username}
            )
        
        user.is_active = True
        user.save()
        login (self.request, user)
        
        return super().get(request, *args, **kwargs)


class PostView(LoginRequiredMixin, CreateView):
    model = Post
    form_class = PostForm
    success_url = reverse_lazy("home")

    def form_valid(self, form):
        self.object = form.save(commit=False)
        self.object.user = self.request.user
        self.object.save()
        return HttpResponseRedirect(self.get_success_url())
    
    def form_valid(self, form):
        self.object = form.save(commit=False)
        self.object.user = self.request.user

        # 投稿された画像データを取得
        image = PIL.Image.open(self.request.FILES['img']).convert('RGB')

        # 縦か横の長い方の辺の長さを取得
        long_side = max(image.size[0], image.size[1])
        # 長編が1920pxより長ければ、1920pxに圧縮
        if long_side > 1920:
            resize_ratio = max(image.size[0] / 1920, image.size[1] / 1920)
            image = image.resize((
                int(image.size[0] / resize_ratio),
                int(image.size[1] / resize_ratio)
            ))

        image_io = io.BytesIO()
        image.save(image_io, format="JPEG")
        # 画像データの保存先を取得
        save_path = "media/" + str(self.request.FILES['img'])
        # 画像オブジェクトから、ImageFieldへの保存に適した型へ変換
        image_file = InMemoryUploadedFile(
            image_io,
            field_name = None,
            name = save_path,
            content_type = "image/jpeg",
            size = image_io.getbuffer().nbytes,
            charset = None,
        )

        self.object.img = image_file
        self.object.save()

        return HttpResponseRedirect(self.get_success_url())



class PostDeleteView(LoginRequiredMixin, DeleteView):
    model = Post
    form_class = ConfirmForm
    success_url = reverse_lazy("home")

    def get_queryset(self):
        return super().get_queryset().filter(user=self.request.user)


class PostDetailView(LoginRequiredMixin, DetailView):
    model = Post

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .select_related("user")
        )


class ProfileEditView(LoginRequiredMixin, UpdateView):
    template_name = "main/edit_profile.html"
    model = User
    form_class = ProfileEditForm
    success_url = reverse_lazy("settings")

    def get_object(self, queryset=None):
        return self.request.user


class FollowMixin:
    def post(self, request, *args, **kwargs):
        target = get_object_or_404(User, pk=self.request.POST.get("target", 0))
        if "follow" in self.request.POST:
            self.request.user.follow.add(target)
        elif "unfollow" in self.request.POST:
            self.request.user.follow.remove(target)
        return HttpResponseRedirect(self.request.META.get("HTTP_REFERER"))


class ProfileView(LoginRequiredMixin, FollowMixin, DetailView):
    model = User

    def get_queryset(self):
        queryset = (
            User.objects.filter(pk=self.kwargs["pk"])
            .prefetch_related("posts", "like")
            .annotate(
                Count("posts", distinct=True),
                Count("follow", distinct=True),
                Count("followed", distinct=True),
            )
        )
        if self.kwargs["pk"] != self.request.user.pk:
            follow_list = self.request.user.follow.all().values_list(
                "id", flat=True
            )
            queryset = queryset.annotate(
                is_follow=Case(
                    When(id__in=follow_list, then=True),
                    default=False,
                )
            )
        return queryset


class FollowListView(LoginRequiredMixin, FollowMixin, ListView):
    template_name = "main/follow_list.html"
    ordering = ("username",)
    paginate_by = 20

    def get_queryset(self):
        user = get_object_or_404(User, pk=self.kwargs["pk"])
        if "followed" in self.request.GET:
            queryset = user.followed
        else:
            queryset = user.follow
        follow_list = self.request.user.follow.all().values_list(
            "id", flat=True
        )
        self.queryset = queryset.annotate(
            is_follow=Case(
                When(id__in=follow_list, then=True),
                default=False,
            )
        )
        return super().get_queryset()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["user_id"] = self.kwargs["pk"]
        return context


class SearchView(LoginRequiredMixin, FollowMixin, ListView):
    template_name = "main/search.html"
    paginate_by = 20

    def get_queryset(self):
        form = SearchForm(self.request.GET)
        if form.is_valid():
            keyword = form.cleaned_data["keyword"]
            if "post" in self.request.GET:
                queryset = self._search_posts(keyword)
            else:
                queryset = self._search_users(keyword)
        else:
            if "post" in self.request.GET:
                queryset = Post.objects.none()
            else:
                queryset = User.objects.none()
        return queryset

    def _search_posts(self, keyword):
        queryset = Post.objects.all().select_related("user")

        for word in keyword.split():
            queryset = queryset.filter(note__icontains=word)
        return queryset.order_by("-post_date")

    def _search_users(self, keyword):
        follow_list = self.request.user.follow.all().values_list(
            "id", flat=True
        )
        queryset = User.objects.all().annotate(
            is_follow=Case(
                When(id__in=follow_list, then=True),
                default=False,
            )
        )

        for word in keyword.split():
            queryset = queryset.filter(username__icontains=word)
        return queryset.order_by("-is_follow", "username")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if "keyword" in self.request.GET:
            context["form"] = SearchForm(self.request.GET)
        else:
            context["form"] = SearchForm()
        return context


class PostLikeAPIView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        try:
            post = Post.objects.get(pk=self.kwargs["pk"])
            if post in self.request.user.like.all():
                self.request.user.like.remove(post)
            else:
                self.request.user.like.add(post)
            result = "success"
        except Post.DoesNotExist:
            result = "DoesNotExist"
        return JsonResponse({"result": result})
    
class CommentView(LoginRequiredMixin, CreateView):
    model = Comment
    template_name = "main/comment_form.html"
    form_class = CommentForm
    success_url = reverse_lazy("home")

    def get_form_kwargs(self):
        post = get_object_or_404(Post, pk=self.kwargs["post_pk"])
        self.object = self.model(user=self.request.user, post=post)
        return super().get_form_kwargs()
    def form_valid(self, form):
        form.instance.user = self.request.user  
        form.instance.post = get_object_or_404(Post, pk=self.kwargs["post_pk"])  
        form.instance.is_anonymous = form.cleaned_data.get("is_anonymous", False)
        return super().form_valid(form)

    

    


